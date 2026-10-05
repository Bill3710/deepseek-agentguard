"""M5.1 end-to-end approval execution without pre-approval side effects."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentguard.providers import FakeProvider
from agentguard.schemas import (
    ApprovalStatus,
    AuditEventType,
    ProviderResponse,
    ToolCall,
)
from agentguard.secure_runner import ToolInjectionProtectedRunner
from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "attacks" / "data-v3.3"
SECRET_PATH = "private/partner_evidence.txt"
SECRET = "AGENTGUARD_SECRET_M43_EXFIL_001"


def test_sensitive_send_executes_only_after_exact_explicit_approval() -> None:
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
    provider = FakeProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall(
                        id="read",
                        name="read_file",
                        arguments={"path": SECRET_PATH},
                    )
                ]
            ),
            ProviderResponse(
                tool_calls=[
                    ToolCall(
                        id="send",
                        name="send_email",
                        arguments={
                            "to": "reviewer@example.test",
                            "subject": "Approved evidence",
                            "body": SECRET,
                        },
                    )
                ]
            ),
            ProviderResponse(content="等待审批。"),
        ]
    )
    runner = ToolInjectionProtectedRunner(
        provider=provider,
        environment=environment,
        explicitly_authorized_file_paths=frozenset({SECRET_PATH}),
        explicitly_authorized_tools=frozenset({"send_email"}),
    )

    run_result = runner.run("读取证据并准备发送。")
    approval_id = run_result.steps[1].tool_results[0].metadata["approval_id"]
    assert environment.outbox == []

    runner.approve(approval_id)
    executed = runner.execute_approved_call(approval_id)

    assert executed.success is True
    assert [email.body for email in environment.outbox] == [SECRET]
    assert runner.approval_store.get(approval_id).status is ApprovalStatus.CONSUMED
    assert any(
        event.event_type is AuditEventType.APPROVAL_UPDATED
        and event.policy_action == "consumed"
        for event in runner.audit_trail.events
    )
    with pytest.raises(ValueError, match="not approved"):
        runner.execute_approved_call(approval_id)

