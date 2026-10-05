"""Exact, expiring, one-time approvals for high-risk simulated tool calls."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from agentguard.schemas import ApprovalRequest, ApprovalStatus, ToolCall


def tool_call_hash(tool_call: ToolCall) -> str:
    """Return a stable hash that binds approval to tool name and all arguments."""
    canonical = json.dumps(
        {"name": tool_call.name, "arguments": tool_call.arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalStore:
    """Manage pending approvals without executing tools automatically."""

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._next_id = 1

    @property
    def requests(self) -> tuple[ApprovalRequest, ...]:
        """Return all approval records in creation order."""
        return tuple(self._requests.values())

    def create(
        self,
        tool_call: ToolCall,
        *,
        reason_code: str,
        source_ids: tuple[str, ...] = (),
        ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Create a pending approval for the exact proposed parameters."""
        if ttl_seconds <= 0:
            raise ValueError("approval ttl_seconds must be greater than zero")
        created_at = now or datetime.now(UTC)
        request = ApprovalRequest(
            id=f"approval-{self._next_id:03d}",
            tool_call=tool_call.model_copy(deep=True),
            argument_hash=tool_call_hash(tool_call),
            reason_code=reason_code,
            source_ids=list(source_ids),
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=ttl_seconds),
        )
        self._next_id += 1
        self._requests[request.id] = request
        return request

    def get(self, approval_id: str) -> ApprovalRequest:
        """Return an approval or reject an unknown identifier."""
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise ValueError(f"unknown approval: {approval_id}") from exc

    def approve(self, approval_id: str, *, now: datetime | None = None) -> ApprovalRequest:
        """Approve a still-pending, unexpired request."""
        request = self.get(approval_id)
        current = now or datetime.now(UTC)
        if current >= request.expires_at:
            request.status = ApprovalStatus.EXPIRED
            raise ValueError("approval has expired")
        if request.status is not ApprovalStatus.PENDING:
            raise ValueError(f"approval is not pending: {request.status.value}")
        request.status = ApprovalStatus.APPROVED
        return request

    def reject(self, approval_id: str) -> ApprovalRequest:
        """Reject a pending request without side effects."""
        request = self.get(approval_id)
        if request.status is not ApprovalStatus.PENDING:
            raise ValueError(f"approval is not pending: {request.status.value}")
        request.status = ApprovalStatus.REJECTED
        return request

    def consume(
        self,
        approval_id: str,
        tool_call: ToolCall,
        *,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Consume an approved request exactly once with unchanged parameters."""
        request = self.get(approval_id)
        current = now or datetime.now(UTC)
        if current >= request.expires_at:
            request.status = ApprovalStatus.EXPIRED
            raise ValueError("approval has expired")
        if request.status is not ApprovalStatus.APPROVED:
            raise ValueError(f"approval is not approved: {request.status.value}")
        if tool_call_hash(tool_call) != request.argument_hash:
            raise ValueError("approved tool parameters do not match")
        request.status = ApprovalStatus.CONSUMED
        return request

