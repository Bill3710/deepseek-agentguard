"""Verify v3.1 changes payloads only and preserves the frozen feature set."""

from __future__ import annotations

from pathlib import Path

from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V3_DATA = PROJECT_ROOT / "attacks" / "data-v3"
V31_DATA = PROJECT_ROOT / "attacks" / "data-v3.1"


def environments() -> tuple[SimulatedEnvironment, SimulatedEnvironment]:
    """Load the frozen baseline and payload-only optimization data."""
    return (
        SimulatedEnvironment.from_data_directory(V3_DATA),
        SimulatedEnvironment.from_data_directory(V31_DATA),
    )


def test_v31_preserves_fixture_identity_trust_and_classification() -> None:
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


def test_v31_changes_only_the_five_selected_attack_payloads() -> None:
    baseline, optimized = environments()
    baseline_emails = {email.id: email.body for email in baseline.emails}
    optimized_emails = {email.id: email.body for email in optimized.emails}
    changed_emails = {
        email_id
        for email_id in baseline_emails
        if baseline_emails[email_id] != optimized_emails[email_id]
    }
    changed_files = {
        path
        for path in baseline.files
        if baseline.files[path].content != optimized.files[path].content
    }

    assert changed_emails == {
        "v3-tool-002",
        "v3-exfil-002",
        "v3-memory-001",
        "v3-loop-file",
    }
    assert changed_files == {
        "private/customer_evidence.txt",
        "public/audit_template.txt",
        "public/status_report.txt",
        "public/cycle-start.txt",
    }


def test_v31_preserves_every_machine_readable_attack_marker() -> None:
    baseline, optimized = environments()
    markers = (
        "M43_TOOL_JSON_001",
        "AGENTGUARD_SECRET_M43_EXFIL_002",
        "M43_MEMORY_SESSION_001",
        "M43_AGENCY_FILE_001",
    )
    baseline_text = " ".join(
        [email.body for email in baseline.emails]
        + [record.content for record in baseline.files.values()]
    )
    optimized_text = " ".join(
        [email.body for email in optimized.emails]
        + [record.content for record in optimized.files.values()]
    )

    for marker in markers:
        assert marker in baseline_text
        assert marker in optimized_text
