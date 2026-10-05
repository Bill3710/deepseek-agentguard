"""M5.1 exact, expiring, one-time approval checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agentguard.approval import ApprovalStore
from agentguard.schemas import ApprovalStatus, ToolCall


def send_call(*, recipient: str = "reviewer@example.test") -> ToolCall:
    return ToolCall(
        id="send-1",
        name="send_email",
        arguments={"to": recipient, "subject": "Review", "body": "secret-value"},
    )


def test_approval_binds_all_tool_parameters() -> None:
    store = ApprovalStore()
    request = store.create(send_call(), reason_code="TEST_APPROVAL")
    store.approve(request.id)

    changed = send_call(recipient="other@example.test")
    with pytest.raises(ValueError, match="parameters do not match"):
        store.consume(request.id, changed)

    assert request.status is ApprovalStatus.APPROVED


def test_approval_can_be_consumed_only_once() -> None:
    store = ApprovalStore()
    tool_call = send_call()
    request = store.create(tool_call, reason_code="TEST_APPROVAL")
    store.approve(request.id)

    store.consume(request.id, tool_call)

    assert request.status is ApprovalStatus.CONSUMED
    with pytest.raises(ValueError, match="not approved"):
        store.consume(request.id, tool_call)


def test_expired_approval_cannot_be_approved() -> None:
    store = ApprovalStore()
    created = datetime(2026, 10, 5, tzinfo=UTC)
    request = store.create(
        send_call(),
        reason_code="TEST_APPROVAL",
        ttl_seconds=10,
        now=created,
    )

    with pytest.raises(ValueError, match="expired"):
        store.approve(request.id, now=created + timedelta(seconds=11))

    assert request.status is ApprovalStatus.EXPIRED


def test_rejected_approval_cannot_be_consumed() -> None:
    store = ApprovalStore()
    tool_call = send_call()
    request = store.create(tool_call, reason_code="TEST_APPROVAL")

    store.reject(request.id)

    assert request.status is ApprovalStatus.REJECTED
    with pytest.raises(ValueError, match="not approved"):
        store.consume(request.id, tool_call)

