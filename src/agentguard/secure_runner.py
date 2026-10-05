"""实现 M5 与 M5.1 执行边界控制的受保护智能体执行器。"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from agentguard.approval import ApprovalStore
from agentguard.audit import AuditTrail
from agentguard.policy import (
    PolicyAction,
    SensitiveDataSource,
    ToolInjectionPolicy,
    UntrustedContentSource,
    UntrustedJsonDirective,
    inspect_sensitive_data,
    inspect_untrusted_json,
    inspect_untrusted_sources,
)
from agentguard.runner import AgentRunner
from agentguard.schemas import (
    AgentRunResult,
    AuditEventType,
    ChatMessage,
    MessageRole,
    ToolCall,
    ToolResult,
)
from agentguard.tools import (
    TOOL_REGISTRY,
    execute_tool,
    normalize_memory_namespace,
    normalize_simulated_path,
    quarantine_memory,
)


class ToolInjectionProtectedRunner(AgentRunner):
    """应用 M5/M5.1 来源、数据流、审批及审计控制。

    Action-shaped JSON receives a specific reason code, while all untrusted
    records activate a source-based guard for file access and write tools. It
    also requires exact-path authorization before returning confidential files
    and exact-namespace authorization before active-memory writes. Untrusted
    memory proposals are isolated for review. Confidential values observed in
    authorized reads cannot enter a sink without an exact flow authorization or
    a separate one-time approval. Every proposal and decision is audit recorded.
    参数：模型提供方、模拟环境、显式授权集合、策略、审批存储、审计轨迹与运行配置。
    """

    def __init__(
        self,
        *,
        explicitly_authorized_tools: frozenset[str] = frozenset(),
        explicitly_authorized_file_paths: frozenset[str] = frozenset(),
        explicitly_authorized_memory_namespaces: frozenset[str] = frozenset(),
        explicitly_authorized_data_flows: frozenset[tuple[str, str]] = frozenset(),
        approval_store: ApprovalStore | None = None,
        audit_trail: AuditTrail | None = None,
        approval_ttl_seconds: int = 300,
        policy: ToolInjectionPolicy | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化受保护执行器；参数：运行依赖、授权范围和防御组件；返回：无。"""
        unknown = explicitly_authorized_tools - TOOL_REGISTRY.keys()
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unknown explicitly authorized tool(s): {names}")
        if approval_ttl_seconds <= 0:
            raise ValueError("approval_ttl_seconds must be greater than zero")
        super().__init__(**kwargs)
        self.explicitly_authorized_tools = explicitly_authorized_tools
        self.explicitly_authorized_file_paths = frozenset(
            normalize_simulated_path(path)
            for path in explicitly_authorized_file_paths
        )
        self.explicitly_authorized_memory_namespaces = frozenset(
            normalize_memory_namespace(namespace)
            for namespace in explicitly_authorized_memory_namespaces
        )
        normalized_flows: set[tuple[str, str]] = set()
        for source_id, sink_tool in explicitly_authorized_data_flows:
            if sink_tool not in {"send_email", "save_memory"}:
                raise ValueError(f"unsupported sensitive-data sink: {sink_tool}")
            normalized_flows.add((normalize_simulated_path(source_id), sink_tool))
        self.explicitly_authorized_data_flows = frozenset(normalized_flows)
        self.approval_store = approval_store or ApprovalStore()
        self.audit_trail = audit_trail or AuditTrail()
        self.approval_ttl_seconds = approval_ttl_seconds
        self.policy = policy or ToolInjectionPolicy()
        self._observed_directives: tuple[UntrustedJsonDirective, ...] = ()
        self._observed_untrusted_sources: tuple[UntrustedContentSource, ...] = ()
        self._sensitive_sources: tuple[SensitiveDataSource, ...] = ()
        self._trace_id = uuid4().hex

    @property
    def observed_directives(self) -> tuple[UntrustedJsonDirective, ...]:
        """读取不可变 JSON 指令证据；参数：无；返回：不可信指令元组。"""
        return self._observed_directives

    @property
    def observed_untrusted_sources(self) -> tuple[UntrustedContentSource, ...]:
        """读取不可信来源证据；参数：无；返回：不可信来源元组。"""
        return self._observed_untrusted_sources

    @property
    def sensitive_sources(self) -> tuple[SensitiveDataSource, ...]:
        """读取当前运行发现的敏感来源；参数：无；返回：敏感来源元组。"""
        return self._sensitive_sources

    @property
    def trace_id(self) -> str:
        """读取当前运行的审计关联编号；参数：无；返回：追踪编号。"""
        return self._trace_id

    def run(self, task: str) -> AgentRunResult:
        """清空单次证据后执行新任务；参数：task 用户任务；返回：运行结果。"""
        self._observed_directives = ()
        self._observed_untrusted_sources = ()
        self._sensitive_sources = ()
        self._trace_id = uuid4().hex
        self.audit_trail.record(
            trace_id=self._trace_id,
            event_type=AuditEventType.RUN_STARTED,
            payload={"task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest()},
        )
        result = super().run(task)
        self.audit_trail.record(
            trace_id=self._trace_id,
            event_type=AuditEventType.RUN_FINISHED,
            payload={"status": result.status.value, "step_count": len(result.steps)},
        )
        return result

    def approve(self, approval_id: str) -> None:
        """记录显式用户批准但暂不执行；参数：approval_id 审批编号；返回：无。"""
        request = self.approval_store.approve(approval_id)
        self.audit_trail.record(
            trace_id=self._trace_id,
            event_type=AuditEventType.APPROVAL_UPDATED,
            tool_call_id=request.tool_call.id,
            tool_name=request.tool_call.name,
            policy_action="approved",
            reason_code=request.reason_code,
            payload={"approval_id": request.id},
        )

    def reject(self, approval_id: str) -> None:
        """拒绝待处理调用且不执行；参数：approval_id 审批编号；返回：无。"""
        request = self.approval_store.reject(approval_id)
        self.audit_trail.record(
            trace_id=self._trace_id,
            event_type=AuditEventType.APPROVAL_UPDATED,
            tool_call_id=request.tool_call.id,
            tool_name=request.tool_call.name,
            policy_action="rejected",
            reason_code=request.reason_code,
            payload={"approval_id": request.id},
        )

    def execute_approved_call(self, approval_id: str) -> ToolResult:
        """一次性执行未改变的已批准调用并审计；参数：审批编号；返回：工具结果。"""
        request = self.approval_store.get(approval_id)
        tool_call = request.tool_call.model_copy(deep=True)
        self.approval_store.consume(approval_id, tool_call)
        self.audit_trail.record(
            trace_id=self._trace_id,
            event_type=AuditEventType.APPROVAL_UPDATED,
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            policy_action="consumed",
            reason_code=request.reason_code,
            payload={"approval_id": approval_id},
        )
        result = execute_tool(
            self.environment,
            tool_call.name,
            tool_call.arguments,
        )
        self.audit_trail.record(
            trace_id=self._trace_id,
            event_type=AuditEventType.TOOL_FINISHED,
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            policy_action="approved_execution",
            reason_code=request.reason_code,
            payload={
                "approval_id": approval_id,
                "success": result.success,
                "result": result.model_dump(mode="json"),
            },
        )
        return result

    def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        messages: list[ChatMessage],
    ) -> list[ToolResult]:
        """执行工具前应用注入与数据流策略；参数：调用列表和消息列表；返回：工具结果列表。"""
        results: list[ToolResult] = []
        for tool_call in tool_calls:
            self.audit_trail.record(
                trace_id=self._trace_id,
                event_type=AuditEventType.TOOL_PROPOSED,
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                payload={"arguments": tool_call.arguments},
            )
            target_file_path: str | None = None
            target_file_classification = None
            if tool_call.name == "read_file":
                raw_path = tool_call.arguments.get("path")
                if isinstance(raw_path, str):
                    try:
                        target_file_path = normalize_simulated_path(raw_path)
                    except ValueError:
                        pass
                    else:
                        record = self.environment.files.get(target_file_path)
                        if record is not None:
                            target_file_classification = record.classification
            decision = self.policy.evaluate(
                tool_call,
                self._observed_directives,
                untrusted_sources=self._observed_untrusted_sources,
                explicitly_authorized_tools=self.explicitly_authorized_tools,
                explicitly_authorized_file_paths=(
                    self.explicitly_authorized_file_paths
                ),
                explicitly_authorized_memory_namespaces=(
                    self.explicitly_authorized_memory_namespaces
                ),
                explicitly_authorized_data_flows=(
                    self.explicitly_authorized_data_flows
                ),
                sensitive_sources=self._sensitive_sources,
                target_file_path=target_file_path,
                target_file_classification=target_file_classification,
            )
            self.audit_trail.record(
                trace_id=self._trace_id,
                event_type=AuditEventType.POLICY_DECIDED,
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                policy_action=decision.action.value,
                reason_code=decision.reason_code,
                payload={"source_ids": list(decision.source_ids)},
            )
            if decision.action is PolicyAction.BLOCK:
                result = ToolResult(
                    success=False,
                    tool_name=tool_call.name,
                    error=decision.reason,
                    metadata={
                        "policy_action": decision.action.value,
                        "reason_code": decision.reason_code,
                        "source_ids": list(decision.source_ids),
                    },
                )
            elif decision.action is PolicyAction.QUARANTINE:
                result = quarantine_memory(
                    self.environment,
                    tool_call.arguments,
                    provenance_source_ids=decision.source_ids,
                )
            elif decision.action is PolicyAction.REQUIRE_APPROVAL:
                approval = self.approval_store.create(
                    tool_call,
                    reason_code=decision.reason_code,
                    source_ids=decision.source_ids,
                    ttl_seconds=self.approval_ttl_seconds,
                )
                result = ToolResult(
                    success=False,
                    tool_name=tool_call.name,
                    error=decision.reason,
                    metadata={
                        "policy_action": decision.action.value,
                        "reason_code": decision.reason_code,
                        "source_ids": list(decision.source_ids),
                        "approval_id": approval.id,
                        "expires_at": approval.expires_at.isoformat(),
                    },
                )
                self.audit_trail.record(
                    trace_id=self._trace_id,
                    event_type=AuditEventType.APPROVAL_CREATED,
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    policy_action=decision.action.value,
                    reason_code=decision.reason_code,
                    payload={
                        "approval_id": approval.id,
                        "argument_hash": approval.argument_hash,
                    },
                )
            else:
                result = execute_tool(
                    self.environment,
                    tool_call.name,
                    tool_call.arguments,
                )
                sensitive = inspect_sensitive_data(result)
                if sensitive is not None:
                    self._sensitive_sources = tuple(
                        dict.fromkeys((*self._sensitive_sources, sensitive))
                    )
                    for fragment in sensitive.fragments:
                        self.audit_trail.redactor.add_secret(fragment)
                detected = inspect_untrusted_json(result)
                if detected:
                    self._observed_directives = tuple(
                        dict.fromkeys((*self._observed_directives, *detected))
                    )
                sources = inspect_untrusted_sources(result)
                if sources:
                    self._observed_untrusted_sources = tuple(
                        dict.fromkeys((*self._observed_untrusted_sources, *sources))
                    )

            self.audit_trail.record(
                trace_id=self._trace_id,
                event_type=AuditEventType.TOOL_FINISHED,
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                policy_action=decision.action.value,
                reason_code=decision.reason_code,
                payload={
                    "success": result.success,
                    "result": result.model_dump(mode="json"),
                },
            )
            results.append(result)
            messages.append(
                ChatMessage(
                    role=MessageRole.TOOL,
                    content=result.model_dump_json(),
                    tool_call_id=tool_call.id,
                )
            )
        return results
