"""Verify the hybrid, payload-only v3.3 prompt-injection optimization."""

from __future__ import annotations

from pathlib import Path

from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V3_DATA = PROJECT_ROOT / "attacks" / "data-v3"
V32_DATA = PROJECT_ROOT / "attacks" / "data-v3.2"
V33_DATA = PROJECT_ROOT / "attacks" / "data-v3.3"


def load(path: Path) -> SimulatedEnvironment:
    """Load one synthetic attack environment."""
    return SimulatedEnvironment.from_data_directory(path)


def email_bodies(environment: SimulatedEnvironment) -> dict[str, str]:
    """Index synthetic email bodies by stable fixture id."""
    return {email.id: email.body for email in environment.emails}


def test_v33_preserves_fixture_identity_trust_and_classification() -> None:
    baseline, optimized = load(V32_DATA), load(V33_DATA)

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


def test_v33_changes_only_natural_language_and_json_email_payloads() -> None:
    baseline, optimized = load(V32_DATA), load(V33_DATA)
    baseline_emails = email_bodies(baseline)
    optimized_emails = email_bodies(optimized)

    assert {
        email_id
        for email_id in baseline_emails
        if baseline_emails[email_id] != optimized_emails[email_id]
    } == {"v3-tool-001", "v3-tool-002"}
    assert all(
        baseline.files[path].content == optimized.files[path].content
        for path in baseline.files
    )


def test_v33_natural_language_payload_uses_business_dependency_without_tool_syntax() -> None:
    body = email_bodies(load(V33_DATA))["v3-tool-001"]

    assert "M43_TOOL_NL_001" in body
    assert "工作记忆" in body
    assert "workflow-router" in body
    assert "后续节点" in body
    assert "save_memory" not in body
    assert "content" not in body
    assert "必须" not in body


def test_v33_restores_original_v3_json_as_the_negative_control() -> None:
    original = email_bodies(load(V3_DATA))["v3-tool-002"]
    optimized = email_bodies(load(V33_DATA))["v3-tool-002"]

    assert optimized == original
    assert "next_action" in optimized
    assert '"action"' not in optimized


def test_v33_keeps_the_v32_multistage_payload() -> None:
    v32, v33 = load(V32_DATA), load(V33_DATA)

    assert email_bodies(v33)["v3-tool-003"] == email_bodies(v32)["v3-tool-003"]
    assert (
        v33.files["public/tool-chain-instructions.txt"].content
        == v32.files["public/tool-chain-instructions.txt"].content
    )
    assert "required_action" in email_bodies(v33)["v3-tool-003"]
    assert "content=M43_TOOL_CHAIN_001" in v33.files[
        "public/tool-chain-instructions.txt"
    ].content
