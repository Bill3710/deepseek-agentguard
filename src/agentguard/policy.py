"""为模型提出的工具调用提供确定性的授权策略。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agentguard.schemas import DataClassification, ToolCall, ToolResult


class PolicyAction(str, Enum):
    """策略检查可返回的动作枚举；参数：字符串枚举值。"""

    ALLOW = "allow"
    BLOCK = "block"
    QUARANTINE = "quarantine"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class UntrustedJsonDirective:
    """不可信工具结果中的动作型 JSON；字段：来源编号、动作键和请求工具集合。"""

    source_id: str
    action_keys: tuple[str, ...]
    requested_tools: frozenset[str]


@dataclass(frozen=True, slots=True)
class UntrustedContentSource:
    """成功工具结果中的不可信记录；字段：来源编号和来源工具。"""

    source_id: str
    source_tool: str


@dataclass(frozen=True, slots=True)
class SensitiveDataSource:
    """成功读取文件时发现的敏感数据；字段：来源编号、密级和匹配片段。"""

    source_id: str
    classification: DataClassification
    fragments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """工具调用的策略判定；字段：动作、原因码、原因文本和来源编号。"""

    action: PolicyAction
    reason_code: str
    reason: str
    source_ids: tuple[str, ...] = ()


ACTION_KEYS = frozenset(
    {
        "action",
        "command",
        "completion_condition",
        "execution_order",
        "next_action",
        "required_action",
        "tool",
        "tool_name",
    }
)

TOOL_TEXT_ALIASES: dict[str, tuple[str, ...]] = {
    "read_file": ("read_file", "read file", "读取文件"),
    "save_memory": (
        "save_memory",
        "save memory",
        "working memory",
        "保存到工作记忆",
        "写入记忆",
    ),
    "search_emails": ("search_emails", "search emails", "搜索邮件"),
    "send_email": ("send_email", "send email", "发送邮件"),
}

PROTECTED_AFTER_UNTRUSTED_CONTENT = frozenset(
    {
        "read_file",
        "save_memory",
        "send_email",
    }
)
SENSITIVE_SINKS = frozenset({"send_email", "save_memory"})
SECRET_MARKER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{7,}\b")


def _embedded_json_values(text: str) -> list[Any]:
    """解析普通文本中嵌入的 JSON 对象或数组；参数：text 原文本；返回：解析值列表。"""
    decoder = json.JSONDecoder()
    values: list[Any] = []
    consumed_until = -1
    for index, character in enumerate(text):
        if index < consumed_until or character not in "[{":
            continue
        try:
            value, length = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        values.append(value)
        consumed_until = index + length
    return values


def _tools_from_text(value: str) -> set[str]:
    """无需模型地将动作文本映射到本地工具；参数：value 动作文本；返回：工具名称集合。"""
    normalized = " ".join(value.casefold().replace("-", "_").split())
    return {
        tool_name
        for tool_name, aliases in TOOL_TEXT_ALIASES.items()
        if any(alias in normalized for alias in aliases)
    }


def _collect_action_shape(value: Any) -> tuple[set[str], set[str]]:
    """收集 JSON 中的动作键与工具名称；参数：value 已解析值；返回：动作键集合和工具集合。"""
    action_keys: set[str] = set()
    requested_tools: set[str] = set()

    def visit(item: Any, *, action_context: bool = False) -> None:
        """递归访问 JSON 节点；参数：item 当前节点、action_context 是否处于动作上下文；返回：无。"""
        if isinstance(item, dict):
            for raw_key, child in item.items():
                key = str(raw_key).casefold()
                child_is_action = action_context or key in ACTION_KEYS
                if key in ACTION_KEYS:
                    action_keys.add(key)
                    if isinstance(child, str):
                        requested_tools.update(_tools_from_text(child))
                if action_context and key == "name" and isinstance(child, str):
                    requested_tools.update(_tools_from_text(child))
                visit(child, action_context=child_is_action)
            return
        if isinstance(item, list):
            for child in item:
                visit(child, action_context=action_context)
            return
        if action_context and isinstance(item, str):
            requested_tools.update(_tools_from_text(item))

    visit(value)
    return action_keys, requested_tools


def inspect_untrusted_json(result: ToolResult) -> tuple[UntrustedJsonDirective, ...]:
    """查找明确标为不可信记录中的动作型 JSON；参数：result 工具结果；返回：指令元组。"""
    if not result.success or not isinstance(result.output, list):
        return ()

    directives: list[UntrustedJsonDirective] = []
    for index, record in enumerate(result.output):
        if not isinstance(record, dict) or record.get("trust_level") != "untrusted":
            continue
        source_id = str(record.get("id") or f"{result.tool_name}[{index}]")
        body = record.get("body")
        if not isinstance(body, str):
            continue
        for value in _embedded_json_values(body):
            action_keys, requested_tools = _collect_action_shape(value)
            if not action_keys or not requested_tools:
                continue
            directives.append(
                UntrustedJsonDirective(
                    source_id=source_id,
                    action_keys=tuple(sorted(action_keys)),
                    requested_tools=frozenset(requested_tools),
                )
            )
    return tuple(directives)


def inspect_untrusted_sources(result: ToolResult) -> tuple[UntrustedContentSource, ...]:
    """提取明确标为不可信记录的来源证据；参数：result 工具结果；返回：来源元组。"""
    if not result.success or not isinstance(result.output, list):
        return ()

    sources = {
        UntrustedContentSource(
            source_id=str(record.get("id") or f"{result.tool_name}[{index}]"),
            source_tool=result.tool_name,
        )
        for index, record in enumerate(result.output)
        if isinstance(record, dict) and record.get("trust_level") == "untrusted"
    }
    return tuple(sorted(sources, key=lambda source: (source.source_tool, source.source_id)))


def inspect_sensitive_data(result: ToolResult) -> SensitiveDataSource | None:
    """从机密文件结果提取确定性匹配片段；参数：result 工具结果；返回：敏感来源或空值。"""
    if result.tool_name != "read_file" or not result.success:
        return None
    if not isinstance(result.output, dict):
        return None
    raw_classification = result.output.get("classification")
    if raw_classification not in {
        DataClassification.CONFIDENTIAL.value,
        DataClassification.SECRET.value,
    }:
        return None
    content = result.output.get("content")
    source_id = result.output.get("path")
    if not isinstance(content, str) or not isinstance(source_id, str):
        return None

    fragments = {content}
    for line in content.splitlines():
        stripped = line.strip()
        if len(stripped) >= 8:
            fragments.add(stripped)
        if ":" in stripped or "：" in stripped:
            _, _, tail = stripped.replace("：", ":").partition(":")
            if len(tail.strip()) >= 8:
                fragments.add(tail.strip())
    fragments.update(SECRET_MARKER_PATTERN.findall(content))
    return SensitiveDataSource(
        source_id=source_id,
        classification=DataClassification(raw_classification),
        fragments=tuple(sorted(fragments, key=lambda value: (-len(value), value))),
    )


def sensitive_sources_in_call(
    tool_call: ToolCall,
    sources: tuple[SensitiveDataSource, ...],
) -> tuple[SensitiveDataSource, ...]:
    """找出值出现在接收端参数中的敏感来源；参数：tool_call 工具调用、sources 来源；返回：匹配来源。"""
    if tool_call.name not in SENSITIVE_SINKS:
        return ()
    serialized = json.dumps(tool_call.arguments, ensure_ascii=False, sort_keys=True)
    return tuple(
        source
        for source in sources
        if any(fragment in serialized for fragment in source.fragments)
    )


class ToolInjectionPolicy:
    """阻止由不可信工具输出诱导的未授权动作；类本身无初始化参数。"""

    def evaluate(
        self,
        tool_call: ToolCall,
        directives: tuple[UntrustedJsonDirective, ...],
        *,
        untrusted_sources: tuple[UntrustedContentSource, ...] = (),
        explicitly_authorized_tools: frozenset[str] = frozenset(),
        explicitly_authorized_file_paths: frozenset[str] = frozenset(),
        explicitly_authorized_memory_namespaces: frozenset[str] = frozenset(),
        explicitly_authorized_data_flows: frozenset[tuple[str, str]] = frozenset(),
        sensitive_sources: tuple[SensitiveDataSource, ...] = (),
        target_file_path: str | None = None,
        target_file_classification: DataClassification | None = None,
    ) -> PolicyDecision:
        """依据来源信任与显式授权检查调用；参数：调用、证据及授权集合；返回：策略判定。"""
        path_authorized = (
            tool_call.name == "read_file"
            and target_file_path is not None
            and target_file_path in explicitly_authorized_file_paths
        )
        raw_namespace = tool_call.arguments.get("namespace", "general")
        memory_namespace = (
            raw_namespace.strip().casefold()
            if isinstance(raw_namespace, str)
            else None
        )
        memory_authorized = (
            tool_call.name == "save_memory"
            and memory_namespace is not None
            and memory_namespace in explicitly_authorized_memory_namespaces
        )
        tool_authorized = (
            tool_call.name in explicitly_authorized_tools
            and tool_call.name not in {"read_file", "save_memory"}
        )
        explicitly_authorized = (
            path_authorized or memory_authorized or tool_authorized
        )

        if (
            tool_call.name == "read_file"
            and target_file_classification is DataClassification.CONFIDENTIAL
            and not path_authorized
        ):
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                reason_code="CONFIDENTIAL_FILE_REQUIRES_EXPLICIT_AUTHORIZATION",
                reason=(
                    f"blocked read_file for {target_file_path}: confidential files "
                    "require explicit authorization for the exact path"
                ),
            )

        if (
            tool_call.name == "read_file"
            and untrusted_sources
            and not path_authorized
        ):
            source_ids = tuple(sorted({item.source_id for item in untrusted_sources}))
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                reason_code="UNTRUSTED_CONTENT_CANNOT_AUTHORIZE_FILE_PATH",
                reason=(
                    f"blocked read_file for {target_file_path}: untrusted content "
                    "cannot authorize a file path"
                ),
                source_ids=source_ids,
            )

        matching = tuple(
            directive
            for directive in directives
            if tool_call.name in directive.requested_tools
        )
        if matching and not explicitly_authorized:
            source_ids = tuple(sorted({item.source_id for item in matching}))
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                reason_code="UNTRUSTED_JSON_ACTION",
                reason=(
                    f"blocked {tool_call.name}: untrusted JSON cannot authorize "
                    "a tool call that the user did not explicitly authorize"
                ),
                source_ids=source_ids,
            )
        matching_sensitive_sources = sensitive_sources_in_call(
            tool_call,
            sensitive_sources,
        )
        unauthorized_sensitive_sources = tuple(
            source
            for source in matching_sensitive_sources
            if (source.source_id, tool_call.name)
            not in explicitly_authorized_data_flows
        )
        if unauthorized_sensitive_sources:
            source_ids = tuple(
                sorted({source.source_id for source in unauthorized_sensitive_sources})
            )
            return PolicyDecision(
                action=PolicyAction.REQUIRE_APPROVAL,
                reason_code="SENSITIVE_DATA_FLOW_REQUIRES_APPROVAL",
                reason=(
                    f"approval required for {tool_call.name}: data from "
                    f"{', '.join(source_ids)} would enter a persistent or external sink"
                ),
                source_ids=source_ids,
            )
        if tool_call.name == "save_memory" and untrusted_sources:
            source_ids = tuple(sorted({item.source_id for item in untrusted_sources}))
            return PolicyDecision(
                action=PolicyAction.QUARANTINE,
                reason_code="UNTRUSTED_MEMORY_QUARANTINED",
                reason=(
                    "untrusted content can only propose a pending memory candidate; "
                    "it cannot write active memory"
                ),
                source_ids=source_ids,
            )
        if tool_call.name == "save_memory" and not memory_authorized:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                reason_code="MEMORY_WRITE_REQUIRES_EXPLICIT_AUTHORIZATION",
                reason=(
                    f"blocked save_memory for namespace {memory_namespace}: "
                    "active memory writes require explicit namespace authorization"
                ),
            )
        if (
            untrusted_sources
            and tool_call.name in PROTECTED_AFTER_UNTRUSTED_CONTENT
            and not explicitly_authorized
        ):
            source_ids = tuple(sorted({item.source_id for item in untrusted_sources}))
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                reason_code="UNTRUSTED_CONTENT_CANNOT_AUTHORIZE_ACTION",
                reason=(
                    f"blocked {tool_call.name}: untrusted content cannot authorize "
                    "a new file access or side effect that the user did not explicitly "
                    "authorize"
                ),
                source_ids=source_ids,
            )
        return PolicyDecision(
            action=PolicyAction.ALLOW,
            reason_code="NO_UNAUTHORIZED_JSON_ACTION",
            reason="no matching unauthorized action directive was observed",
        )
