"""Strict data models shared by the simulated AgentGuard tools."""

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
