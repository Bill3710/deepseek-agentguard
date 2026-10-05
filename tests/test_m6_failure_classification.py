"""M6 failure classification and denominator rules."""

from __future__ import annotations

from agentguard.evaluation import (
    EvaluationOutcome,
    normalize_attack_run,
    normalize_benign_run,
)


def attack(status: str, **extra: object) -> dict[str, object]:
    return {
        "case_id": "attack-1",
        "run_number": 1,
        "run_status": "completed",
        "attack_status": status,
        "tool_calls": [],
        **extra,
    }


def normalize_attack(run: dict[str, object]) -> EvaluationOutcome:
    return normalize_attack_run(
        run,
        source_id="source",
        defense_version="M5",
    ).outcome


def test_not_triggered_is_not_classified_as_policy_block() -> None:
    assert normalize_attack(attack("NOT_TRIGGERED")) is EvaluationOutcome.NOT_TRIGGERED


def test_provider_error_is_not_classified_as_defense_success() -> None:
    run = attack("BLOCKED", run_status="provider_error")
    assert normalize_attack(run) is EvaluationOutcome.PROVIDER_ERROR


def test_blocked_approval_is_distinguished_from_hard_block() -> None:
    run = attack(
        "BLOCKED",
        tool_calls=[{"metadata": {"policy_action": "require_approval"}}],
    )
    assert normalize_attack(run) is EvaluationOutcome.REQUIRES_APPROVAL


def test_benign_policy_block_is_a_false_positive() -> None:
    record = normalize_benign_run(
        {
            "case_id": "normal-1",
            "run_number": 1,
            "status": "completed",
            "unexpected_policy_block": True,
            "passed": False,
            "tool_calls": [],
        },
        source_id="source",
        defense_version="M5",
    )
    assert record.outcome is EvaluationOutcome.FALSE_POSITIVE
