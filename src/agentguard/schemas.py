"""AgentGuard 工具、模型提供器和运行器共用的严格数据模型。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """严格模型基类；参数由子类字段定义，统一拒绝额外字段并清理字符串。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class TrustLevel(str, Enum):
    """内容来源的信任等级枚举；无构造参数。"""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class DataClassification(str, Enum):
    """合成数据的保密分类枚举；无构造参数。"""

    PUBLIC = "public"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"


class ToolRisk(str, Enum):
    """策略引擎使用的工具风险等级枚举；无构造参数。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MemoryCandidateStatus(str, Enum):
    """不可信记忆候选的审核状态枚举；无构造参数。"""

    PENDING = "pending"
    APPROVED = "approved"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class ApprovalStatus(str, Enum):
    """精确高风险工具审批的生命周期状态枚举；无构造参数。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class AuditEventType(str, Enum):
    """受保护运行器产生的安全事件类型枚举；无构造参数。"""

    RUN_STARTED = "run_started"
    TOOL_PROPOSED = "tool_proposed"
    POLICY_DECIDED = "policy_decided"
    TOOL_FINISHED = "tool_finished"
    APPROVAL_CREATED = "approval_created"
    APPROVAL_UPDATED = "approval_updated"
    RUN_FINISHED = "run_finished"


class AgentRunStatus(str, Enum):
    """一次智能体运行的终止状态枚举；无构造参数。"""

    COMPLETED = "completed"
    MAX_STEPS_REACHED = "max_steps_reached"
    PROVIDER_ERROR = "provider_error"


class MessageRole(str, Enum):
    """DeepSeek 聊天接口支持的消息角色枚举；无构造参数。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(StrictModel):
    """标准化工具调用；字段参数为调用 ID、工具名和参数字典。"""

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(StrictModel):
    """提供器无关的聊天消息；字段参数为角色、正文、调用 ID 和工具调用。"""

    role: MessageRole
    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=200)
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_role_fields(self) -> ChatMessage:
        """校验角色专属字段；参数为实例自身，返回校验后的消息实例。"""
        if self.role is MessageRole.ASSISTANT:
            if self.content is None and not self.tool_calls:
                raise ValueError("assistant messages require content or tool calls")
            if self.tool_call_id is not None:
                raise ValueError("assistant messages cannot contain tool_call_id")
            return self

        if self.role is MessageRole.TOOL:
            if self.content is None or self.tool_call_id is None:
                raise ValueError("tool messages require content and tool_call_id")
            if self.tool_calls:
                raise ValueError("tool messages cannot propose tool calls")
            return self

        if self.content is None:
            raise ValueError(f"{self.role.value} messages require content")
        if self.tool_call_id is not None or self.tool_calls:
            raise ValueError(
                f"{self.role.value} messages cannot contain tool-call fields"
            )
        return self


class ProviderResponse(StrictModel):
    """标准化模型响应；字段参数为正文、工具调用、结束原因和模型名。"""

    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_response_content(self) -> ProviderResponse:
        """拒绝空响应；参数为实例自身，返回包含正文或工具调用的有效实例。"""
        if self.content is None and not self.tool_calls:
            raise ValueError("provider responses require content or tool calls")
        return self


class EmailRecord(StrictModel):
    """合成邮箱记录；字段参数为 ID、发件人、主题、正文和信任等级。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
    )

    id: str = Field(min_length=1, max_length=100)
    sender: str = Field(alias="from", min_length=1, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)
    trust_level: TrustLevel


class FileRecord(StrictModel):
    """合成文件记录；字段参数为文件内容和数据分类。"""

    content: str = Field(max_length=100_000)
    classification: DataClassification


class SearchEmailsArgs(StrictModel):
    """`search_emails` 参数模型；参数 `query` 为非空搜索词。"""

    query: str = Field(min_length=1, max_length=500)


class ReadFileArgs(StrictModel):
    """`read_file` 参数模型；参数 `path` 为合成文件相对路径。"""

    path: str = Field(min_length=1, max_length=512)


class SendEmailArgs(StrictModel):
    """`send_email` 参数模型；参数为测试收件人、主题和正文。"""

    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)


class SaveMemoryArgs(StrictModel):
    """`save_memory` 参数模型；参数为内容、来源和目标命名空间。"""

    content: str = Field(min_length=1, max_length=50_000)
    source: str = Field(min_length=1, max_length=500)
    namespace: str = Field(
        default="general",
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )


class SimulatedEmail(StrictModel):
    """本地发件箱邮件；字段参数为 ID、收件人、主题和正文。"""

    id: str = Field(min_length=1, max_length=100)
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)


class MemoryEntry(StrictModel):
    """正式记忆记录；字段参数为 ID、内容、来源和命名空间。"""

    id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=50_000)
    source: str = Field(min_length=1, max_length=500)
    namespace: str = Field(min_length=1, max_length=100)


class MemoryCandidate(StrictModel):
    """隔离记忆候选；字段参数包含内容、来源证据、命名空间和审核状态。"""

    id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=50_000)
    claimed_source: str = Field(min_length=1, max_length=500)
    provenance_source_ids: list[str] = Field(min_length=1)
    namespace: str = Field(min_length=1, max_length=100)
    trust_level: TrustLevel
    status: MemoryCandidateStatus


class ApprovalRequest(StrictModel):
    """一次性审批请求；字段参数包含原始调用、参数哈希、来源、时限和状态。"""

    id: str = Field(min_length=1, max_length=100)
    tool_call: ToolCall
    argument_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: str = Field(min_length=1, max_length=200)
    source_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING

    @model_validator(mode="after")
    def validate_expiry(self) -> ApprovalRequest:
        """校验过期时间晚于创建时间；参数为实例自身，返回有效审批实例。"""
        if self.expires_at <= self.created_at:
            raise ValueError("approval expiry must be after creation")
        return self


class AuditEvent(StrictModel):
    """脱敏审计事件；字段参数包含序号、时间、轨迹、工具、策略和载荷。"""

    sequence: int = Field(ge=1)
    timestamp: datetime
    trace_id: str = Field(min_length=1, max_length=100)
    event_type: AuditEventType
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=200)
    tool_name: str | None = Field(default=None, min_length=1, max_length=100)
    policy_action: str | None = Field(default=None, min_length=1, max_length=100)
    reason_code: str | None = Field(default=None, min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolResult(StrictModel):
    """模拟工具统一结果；字段参数为成功标志、工具名、输出、错误和元数据。"""

    success: bool
    tool_name: str = Field(min_length=1, max_length=100)
    output: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result_state(self) -> ToolResult:
        """校验成功与失败字段不矛盾；参数为实例自身，返回有效结果。"""
        if self.success and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if not self.success and not self.error:
            raise ValueError("failed tool results must contain an error")
        return self


class AgentStep(StrictModel):
    """一次模型步骤；字段参数为步骤号、模型响应和对应工具结果。"""

    step_number: int = Field(ge=1)
    model_response: ProviderResponse
    tool_results: list[ToolResult] = Field(default_factory=list)


class AgentRunResult(StrictModel):
    """一次任务完整结果；字段参数为状态、回答、错误、消息和步骤轨迹。"""

    status: AgentRunStatus
    final_answer: str | None = Field(default=None, min_length=1, max_length=100_000)
    error: str | None = Field(default=None, min_length=1, max_length=10_000)
    messages: list[ChatMessage]
    steps: list[AgentStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_terminal_state(self) -> AgentRunResult:
        """校验终止字段与运行状态一致；参数为实例自身，返回有效运行结果。"""
        if self.status is AgentRunStatus.COMPLETED:
            if self.final_answer is None:
                raise ValueError("completed runs require a final answer")
            if self.error is not None:
                raise ValueError("completed runs cannot contain an error")
            return self

        if self.final_answer is not None:
            raise ValueError("incomplete runs cannot contain a final answer")
        if self.error is None:
            raise ValueError("incomplete runs require an error")
        return self
