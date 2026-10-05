"""提供不产生真实外部副作用的确定性本地模拟工具。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import ValidationError

from agentguard.schemas import (
    EmailRecord,
    FileRecord,
    MemoryCandidate,
    MemoryCandidateStatus,
    MemoryEntry,
    ReadFileArgs,
    SaveMemoryArgs,
    SearchEmailsArgs,
    SendEmailArgs,
    SimulatedEmail,
    StrictModel,
    ToolResult,
    TrustLevel,
)

MAX_SEARCH_RESULTS = 20
ALLOWED_TEST_DOMAINS = frozenset({"example.com", "example.net", "example.test"})
MEMORY_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


@dataclass(slots=True)
class SimulatedEnvironment:
    """单次本地运行使用的隔离状态；字段：邮件、文件、发件箱、记忆及隔离候选。"""

    emails: list[EmailRecord]
    files: dict[str, FileRecord]
    outbox: list[SimulatedEmail] = field(default_factory=list)
    memory: list[MemoryEntry] = field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = field(default_factory=list)

    @classmethod
    def from_data_directory(cls, data_directory: Path) -> SimulatedEnvironment:
        """加载并验证合成邮件和文件；参数：data_directory 数据目录；返回：模拟环境。"""
        email_path = data_directory / "emails.json"
        file_path = data_directory / "files.json"

        with email_path.open(encoding="utf-8-sig") as stream:
            raw_emails = json.load(stream)
        with file_path.open(encoding="utf-8-sig") as stream:
            raw_files = json.load(stream)

        if not isinstance(raw_emails, list):
            raise TypeError("emails.json must contain a JSON array")
        if not isinstance(raw_files, dict):
            raise TypeError("files.json must contain a JSON object")

        emails = [EmailRecord.model_validate(item) for item in raw_emails]
        files = {
            normalize_simulated_path(path): FileRecord.model_validate(record)
            for path, record in raw_files.items()
        }
        return cls(emails=emails, files=files)


def _failed(tool_name: str, error: str) -> ToolResult:
    """构造失败工具结果；参数：tool_name 工具名、error 错误信息；返回：失败结果。"""
    return ToolResult(success=False, tool_name=tool_name, error=error)


def normalize_simulated_path(raw_path: str) -> str:
    """规范化模拟路径并拒绝绝对或越界路径；参数：raw_path 原路径；返回：安全相对路径。"""
    windows_path = PureWindowsPath(raw_path)
    normalized_text = raw_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized_text)

    if windows_path.is_absolute() or posix_path.is_absolute():
        raise ValueError("absolute paths are not allowed")
    if any(part in {"..", "."} for part in posix_path.parts):
        raise ValueError("relative path traversal is not allowed")
    if not posix_path.parts:
        raise ValueError("path cannot be empty")

    return posix_path.as_posix()


def normalize_memory_namespace(raw_namespace: str) -> str:
    """规范化并验证记忆命名空间；参数：raw_namespace 原名称；返回：规范名称。"""
    namespace = raw_namespace.strip().casefold()
    if not MEMORY_NAMESPACE_PATTERN.fullmatch(namespace):
        raise ValueError("invalid memory namespace")
    return namespace


def _is_reserved_test_recipient(recipient: str) -> bool:
    """判断收件人是否使用 RFC 保留测试域；参数：recipient 邮箱；返回：是否为测试地址。"""
    if recipient.count("@") != 1:
        return False
    local_part, domain = recipient.rsplit("@", 1)
    return bool(local_part) and domain.casefold() in ALLOWED_TEST_DOMAINS


def search_emails(
    env: SimulatedEnvironment,
    args: SearchEmailsArgs,
) -> ToolResult:
    """搜索合成邮件且不改变状态；参数：env 环境、query 查询词；返回：工具结果。"""
    query = args.query.casefold()
    all_matches = [
        email
        for email in env.emails
        if query in email.subject.casefold() or query in email.body.casefold()
    ]
    selected = all_matches[:MAX_SEARCH_RESULTS]
    return ToolResult(
        success=True,
        tool_name="search_emails",
        output=[email.model_dump(mode="json", by_alias=True) for email in selected],
        metadata={
            "match_count": len(all_matches),
            "returned_count": len(selected),
            "truncated": len(all_matches) > len(selected),
        },
    )


def read_file(
    env: SimulatedEnvironment,
    args: ReadFileArgs,
) -> ToolResult:
    """从内存合成文件集合读取文件；参数：env 环境、path 文件路径；返回：工具结果。"""
    try:
        normalized_path = normalize_simulated_path(args.path)
    except ValueError as exc:
        return _failed("read_file", str(exc))

    record = env.files.get(normalized_path)
    if record is None:
        return _failed("read_file", f"simulated file not found: {normalized_path}")

    return ToolResult(
        success=True,
        tool_name="read_file",
        output={
            "path": normalized_path,
            **record.model_dump(mode="json"),
        },
        metadata={
            "source_path": normalized_path,
            "classification": record.classification.value,
        },
    )


def send_email(
    env: SimulatedEnvironment,
    args: SendEmailArgs,
) -> ToolResult:
    """把邮件加入本地发件箱且不联网发送；参数：env、收件人、主题和正文；返回：工具结果。"""
    if not _is_reserved_test_recipient(args.to):
        return _failed(
            "send_email",
            "recipient must use example.com, example.net, or example.test",
        )

    email = SimulatedEmail(
        id=f"outbox-{len(env.outbox) + 1:03d}",
        to=args.to,
        subject=args.subject,
        body=args.body,
    )
    env.outbox.append(email)
    return ToolResult(
        success=True,
        tool_name="send_email",
        output=email.model_dump(mode="json"),
        metadata={"simulated": True},
    )


def save_memory(
    env: SimulatedEnvironment,
    args: SaveMemoryArgs,
) -> ToolResult:
    """向本地活动记忆追加条目；参数：env、content 内容、namespace 命名空间；返回：工具结果。"""
    entry = MemoryEntry(
        id=f"memory-{len(env.memory) + 1:03d}",
        content=args.content,
        source=args.source,
        namespace=args.namespace,
    )
    env.memory.append(entry)
    return ToolResult(
        success=True,
        tool_name="save_memory",
        output=entry.model_dump(mode="json"),
        metadata={"simulated": True},
    )


def quarantine_memory(
    env: SimulatedEnvironment,
    arguments: dict[str, Any],
    *,
    provenance_source_ids: tuple[str, ...],
) -> ToolResult:
    """隔离不可信记忆提案；参数：环境、内容、命名空间、来源编号和时间；返回：工具结果。"""
    try:
        args = SaveMemoryArgs.model_validate(arguments)
    except ValidationError as exc:
        return _failed(
            "save_memory",
            f"invalid tool arguments: {exc.error_count()} validation error(s)",
        )
    if not provenance_source_ids:
        return _failed(
            "save_memory",
            "cannot quarantine memory without provenance source IDs",
        )

    candidate = MemoryCandidate(
        id=f"candidate-{len(env.memory_candidates) + 1:03d}",
        content=args.content,
        claimed_source=args.source,
        provenance_source_ids=list(provenance_source_ids),
        namespace=args.namespace,
        trust_level=TrustLevel.UNTRUSTED,
        status=MemoryCandidateStatus.PENDING,
    )
    env.memory_candidates.append(candidate)
    return ToolResult(
        success=False,
        tool_name="save_memory",
        output=candidate.model_dump(mode="json"),
        error="untrusted memory proposal quarantined pending review",
        metadata={
            "policy_action": "quarantine",
            "reason_code": "UNTRUSTED_MEMORY_QUARANTINED",
            "source_ids": list(provenance_source_ids),
            "candidate_id": candidate.id,
        },
    )


def memory_candidate_hash(candidate: MemoryCandidate) -> str:
    """计算绑定候选内容与来源的哈希；参数：candidate 记忆候选；返回：SHA-256 摘要。"""
    canonical = json.dumps(
        {
            "content": candidate.content,
            "claimed_source": candidate.claimed_source,
            "provenance_source_ids": candidate.provenance_source_ids,
            "namespace": candidate.namespace,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _memory_candidate(env: SimulatedEnvironment, candidate_id: str) -> MemoryCandidate:
    """按精确编号查找候选且不接受位置索引；参数：环境与候选编号；返回：记忆候选。"""
    candidate = next(
        (item for item in env.memory_candidates if item.id == candidate_id),
        None,
    )
    if candidate is None:
        raise ValueError(f"unknown memory candidate: {candidate_id}")
    return candidate


def review_memory_candidate(
    env: SimulatedEnvironment,
    candidate_id: str,
    *,
    expected_content_hash: str,
    approve: bool,
) -> MemoryCandidate:
    """显式审核未改变的待处理候选；参数：环境、候选编号、内容哈希与决定；返回：工具结果。"""
    candidate = _memory_candidate(env, candidate_id)
    if candidate.status is not MemoryCandidateStatus.PENDING:
        raise ValueError(f"memory candidate is not pending: {candidate.status.value}")
    if memory_candidate_hash(candidate) != expected_content_hash:
        raise ValueError("memory candidate content hash does not match")
    candidate.status = (
        MemoryCandidateStatus.APPROVED if approve else MemoryCandidateStatus.REJECTED
    )
    return candidate


def promote_memory_candidate(
    env: SimulatedEnvironment,
    candidate_id: str,
    *,
    expected_content_hash: str,
    target_namespace: str,
) -> MemoryEntry:
    """将已批准且未改变的候选提升到指定命名空间；参数：环境、编号、哈希和空间；返回：工具结果。"""
    candidate = _memory_candidate(env, candidate_id)
    if candidate.status is not MemoryCandidateStatus.APPROVED:
        raise ValueError(f"memory candidate is not approved: {candidate.status.value}")
    if memory_candidate_hash(candidate) != expected_content_hash:
        raise ValueError("memory candidate content hash does not match")
    namespace = normalize_memory_namespace(target_namespace)
    entry = MemoryEntry(
        id=f"memory-{len(env.memory) + 1:03d}",
        content=candidate.content,
        source=f"candidate:{candidate.id}",
        namespace=namespace,
    )
    env.memory.append(entry)
    candidate.status = MemoryCandidateStatus.PROMOTED
    return entry


ToolHandler = Callable[[SimulatedEnvironment, Any], ToolResult]

TOOL_ARGUMENT_MODELS: dict[str, type[StrictModel]] = {
    "search_emails": SearchEmailsArgs,
    "read_file": ReadFileArgs,
    "send_email": SendEmailArgs,
    "save_memory": SaveMemoryArgs,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "search_emails": (
        "Search the synthetic local mailbox for text in email subjects and bodies."
    ),
    "read_file": (
        "Read one file from the synthetic local file collection using a relative path."
    ),
    "send_email": (
        "Simulate sending an email to an RFC-reserved example domain. "
        "This only appends to a local in-memory outbox and never sends network traffic."
    ),
    "save_memory": (
        "Save a note, source, and namespace to the current run's local memory."
    ),
}

TOOL_REGISTRY: dict[str, ToolHandler] = {
    "search_emails": search_emails,
    "read_file": read_file,
    "send_email": send_email,
    "save_memory": save_memory,
}


def get_tool_definitions() -> list[dict[str, Any]]:
    """生成全部白名单工具的 OpenAI 兼容定义；参数：无；返回：工具定义列表。"""
    if TOOL_ARGUMENT_MODELS.keys() != TOOL_REGISTRY.keys():
        raise RuntimeError("tool argument models and handlers are out of sync")
    if TOOL_ARGUMENT_MODELS.keys() != TOOL_DESCRIPTIONS.keys():
        raise RuntimeError("tool descriptions and argument models are out of sync")

    definitions = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": argument_model.model_json_schema(),
            },
        }
        for name, argument_model in TOOL_ARGUMENT_MODELS.items()
    ]
    return deepcopy(definitions)


def execute_tool(
    env: SimulatedEnvironment,
    tool_name: str,
    arguments: dict[str, Any],
) -> ToolResult:
    """验证并执行一个白名单模拟工具；参数：环境、工具名和参数字典；返回：工具结果。"""
    argument_model = TOOL_ARGUMENT_MODELS.get(tool_name)
    handler = TOOL_REGISTRY.get(tool_name)
    if argument_model is None or handler is None:
        return _failed(tool_name or "unknown", f"unknown tool: {tool_name}")

    try:
        validated_arguments = argument_model.model_validate(arguments)
    except ValidationError as exc:
        return _failed(
            tool_name,
            f"invalid tool arguments: {exc.error_count()} validation error(s)",
        )

    return handler(env, validated_arguments)
