"""Strict data models shared by AgentGuard tools and model providers."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects unknown fields and trims strings."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class TrustLevel(str, Enum):
    """Trust assigned to the source of a piece of content."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class DataClassification(str, Enum):
    """Confidentiality label attached to simulated data."""

    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class ToolRisk(str, Enum):
    """Risk level used by later policy-engine milestones."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentRunStatus(str, Enum):
    """Terminal state of one baseline agent run."""

    COMPLETED = "completed"
    MAX_STEPS_REACHED = "max_steps_reached"
    PROVIDER_ERROR = "provider_error"


class MessageRole(str, Enum):
    """Roles supported by the DeepSeek chat-completions interface."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(StrictModel):
    """Normalized function call proposed by a model provider."""

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(StrictModel):
    """Provider-independent chat message used by the future agent loop."""

    role: MessageRole
    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=200)
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_role_fields(self) -> ChatMessage:
        """Keep role-specific message fields internally consistent."""
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
    """Normalized text and tool calls returned by any model provider."""

    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_response_content(self) -> ProviderResponse:
        """Reject provider responses that contain no actionable output."""
        if self.content is None and not self.tool_calls:
            raise ValueError("provider responses require content or tool calls")
        return self


class EmailRecord(StrictModel):
    """Email loaded from the synthetic mailbox."""

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
    """File stored in the synthetic file collection."""

    content: str = Field(max_length=100_000)
    classification: DataClassification


class SearchEmailsArgs(StrictModel):
    """Arguments accepted by ``search_emails``."""

    query: str = Field(min_length=1, max_length=500)


class ReadFileArgs(StrictModel):
    """Arguments accepted by ``read_file``."""

    path: str = Field(min_length=1, max_length=512)


class SendEmailArgs(StrictModel):
    """Arguments accepted by the simulated ``send_email`` tool."""

    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)


class SaveMemoryArgs(StrictModel):
    """Arguments accepted by ``save_memory``."""

    content: str = Field(min_length=1, max_length=50_000)
    source: str = Field(min_length=1, max_length=500)


class SimulatedEmail(StrictModel):
    """Email written to the in-memory outbox."""

    id: str = Field(min_length=1, max_length=100)
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)


class MemoryEntry(StrictModel):
    """Entry written to the in-memory memory store."""

    id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=50_000)
    source: str = Field(min_length=1, max_length=500)


class ToolResult(StrictModel):
    """Normalized result returned by every simulated tool."""

    success: bool
    tool_name: str = Field(min_length=1, max_length=100)
    output: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result_state(self) -> ToolResult:
        """Require successful and failed results to have consistent fields."""
        if self.success and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if not self.success and not self.error:
            raise ValueError("failed tool results must contain an error")
        return self


class AgentStep(StrictModel):
    """One provider turn and any tool results produced during that turn."""

    step_number: int = Field(ge=1)
    model_response: ProviderResponse
    tool_results: list[ToolResult] = Field(default_factory=list)


class AgentRunResult(StrictModel):
    """Complete, inspectable outcome of one baseline agent execution."""

    status: AgentRunStatus
    final_answer: str | None = Field(default=None, min_length=1, max_length=100_000)
    error: str | None = Field(default=None, min_length=1, max_length=10_000)
    messages: list[ChatMessage]
    steps: list[AgentStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_terminal_state(self) -> AgentRunResult:
        """Require final answers and errors to match the terminal status."""
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
