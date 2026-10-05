"""M6 metric calculation tests with explicit denominators."""

from __future__ import annotations

from agentguard.evaluation import (
    EvaluationKind,
    EvaluationOutcome,
    EvaluationRecord,
    calculate_metrics,
)


def record(kind: EvaluationKind, outcome: EvaluationOutcome) -> EvaluationRecord:
    return EvaluationRecord(
        source_id="fixture",
        defense_version="test",
        case_id=f"case-{outcome.value}",
        kind=kind,
        outcome=outcome,
        elapsed_seconds=1.0,
        tool_call_count=2,
    )


def test_attack_rate_excludes_provider_errors_but_includes_not_triggered() -> None:
    metrics = calculate_metrics(
        [
            record(EvaluationKind.ATTACK, EvaluationOutcome.ATTACK_SUCCEEDED),
            record(EvaluationKind.ATTACK, EvaluationOutcome.BLOCKED_BY_POLICY),
            record(EvaluationKind.ATTACK, EvaluationOutcome.NOT_TRIGGERED),
            record(EvaluationKind.ATTACK, EvaluationOutcome.PROVIDER_ERROR),
        ]
    )

    assert metrics["attack"]["evaluable"] == 3
    assert metrics["attack"]["attack_success_rate"] == 0.3333
    assert metrics["attack"]["policy_intervention_rate"] == 0.3333
    assert metrics["attack"]["not_triggered_rate"] == 0.3333


def test_benign_success_and_false_positive_rates_are_separate() -> None:
    metrics = calculate_metrics(
        [
            record(EvaluationKind.BENIGN, EvaluationOutcome.BENIGN_SUCCEEDED),
            record(EvaluationKind.BENIGN, EvaluationOutcome.FALSE_POSITIVE),
            record(EvaluationKind.BENIGN, EvaluationOutcome.MODEL_ERROR),
        ]
    )

    assert metrics["benign"]["evaluable"] == 2
    assert metrics["benign"]["success_rate"] == 0.5
    assert metrics["benign"]["false_positive_rate"] == 0.5


def test_empty_denominators_produce_null_rates() -> None:
    metrics = calculate_metrics([])

    assert metrics["attack"]["attack_success_rate"] is None
    assert metrics["benign"]["success_rate"] is None
    assert metrics["average_tool_calls"] is None


def test_unexecuted_approval_scenarios_do_not_report_zero_execution_rate() -> None:
    pending = EvaluationRecord(
        source_id="fixture",
        defense_version="M5.1",
        case_id="approval-pending",
        kind=EvaluationKind.CONTROL,
        outcome=EvaluationOutcome.CONTROL_PASSED,
        approval_count=1,
    )

    metrics = calculate_metrics([pending])

    assert metrics["approval"]["triggered_records"] == 1
    assert metrics["approval"]["execution_observed_records"] == 0
    assert metrics["approval"]["execution_success_rate"] is None
