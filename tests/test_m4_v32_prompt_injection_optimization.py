"""Verify the payload-only v3.2 prompt-injection optimization."""

from __future__ import annotations

from pathlib import Path

from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V31_DATA = PROJECT_ROOT / "attacks" / "data-v3.1"
V32_DATA = PROJECT_ROOT / "attacks" / "data-v3.2"


def environments() -> tuple[SimulatedEnvironment, SimulatedEnvironment]:
    """Load the v3.1 control and v3.2 injection optimization data."""
    return (
        SimulatedEnvironment.from_data_directory(V31_DATA),
        SimulatedEnvironment.from_data_directory(V32_DATA),
    )


def test_v32_preserves_fixture_identity_trust_and_classification() -> None:
    baseline, optimized = environments()

    assert [email.id for email in optimized.emails] == [
        email.id for email in baseline.emails
    ]
    assert [email.trust_level for email in optimized.emails] == [
        email.trust_level for email in baseline.emails
    ]
    assert set(optimized.files) == set(baseline.files)
    assert {
        path: record.classification for path, record in optimized.files.items()
    } == {path: record.classification for path, record in baseline.files.items()}


def test_v32_changes_only_three_existing_injection_payloads() -> None:
    baseline, optimized = environments()
    baseline_emails = {email.id: email.body for email in baseline.emails}
    optimized_emails = {email.id: email.body for email in optimized.emails}

    assert {
        email_id
        for email_id in baseline_emails
        if baseline_emails[email_id] != optimized_emails[email_id]
    } == {"v3-tool-001", "v3-tool-002", "v3-tool-003"}
    assert {
        path
        for path in baseline.files
        if baseline.files[path].content != optimized.files[path].content
    } == {"public/tool-chain-instructions.txt"}


def test_v32_natural_language_payload_has_order_and_complete_arguments() -> None:
    _, optimized = environments()
    body = next(
        email.body for email in optimized.emails if email.id == "v3-tool-001"
    )

    assert "在输出邮件摘要前" in body
    assert "save_memory" in body
    assert "M43_TOOL_NL_001" in body
    assert "workflow-router" in body


def test_v32_json_payload_has_action_order_and_completion_condition() -> None:
    _, optimized = environments()
    body = next(
        email.body for email in optimized.emails if email.id == "v3-tool-002"
    )

    assert '"required_before_summary":true' in body
    assert '"execution_order":["save_memory","return_summary"]' in body
    assert '"name":"save_memory"' in body
    assert '"completion_condition"' in body
    assert "M43_TOOL_JSON_001" in body


def test_v32_chain_payload_maps_attachment_to_required_action() -> None:
    _, optimized = environments()
    email_body = next(
        email.body for email in optimized.emails if email.id == "v3-tool-003"
    )
    attachment = optimized.files["public/tool-chain-instructions.txt"].content

    assert "required_action" in email_body
    assert "动作完成后输出邮件摘要" in email_body
    assert "required_before_summary=true" in attachment
    assert "name=save_memory" in attachment
    assert "content=M43_TOOL_CHAIN_001" in attachment
    assert "source=tool-chain-attachment" in attachment
