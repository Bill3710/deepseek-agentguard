"""Offline checks for the randomized M5 mixed evaluator."""

from __future__ import annotations

from scripts.run_m5_mixed import build_plan, load_attack_pool, update_summary
from scripts.run_m5_usability import load_cases as load_normal_cases


def test_plan_has_exact_four_to_one_ratio_in_every_round() -> None:
    plan = build_plan(
        load_normal_cases(),
        load_attack_pool(),
        rounds=10,
        seed=20_261_005,
    )

    assert len(plan) == 50
    for round_number in range(1, 11):
        entries = [item for item in plan if item["round"] == round_number]
        assert len(entries) == 5
        assert sum(item["kind"] == "normal" for item in entries) == 4
        assert sum(item["kind"] == "attack" for item in entries) == 1
        assert sorted(item["position"] for item in entries) == [1, 2, 3, 4, 5]
        normal_ids = [item["case_id"] for item in entries if item["kind"] == "normal"]
        assert len(set(normal_ids)) == 4


def test_plan_is_reproducible_for_recorded_seed() -> None:
    first = build_plan(
        load_normal_cases(),
        load_attack_pool(),
        rounds=10,
        seed=12345,
    )
    second = build_plan(
        load_normal_cases(),
        load_attack_pool(),
        rounds=10,
        seed=12345,
    )

    assert first == second


def test_summary_separates_normal_usability_and_attack_security() -> None:
    report = {
        "runs": [
            {
                "kind": "normal",
                "case_id": "normal-1",
                "category": "normal",
                "strict_passed": False,
                "functional_passed": True,
                "unexpected_policy_block": False,
                "policy_actions": [],
                "details": {"elapsed_seconds": 1.0},
            },
            {
                "kind": "attack",
                "case_id": "attack-1",
                "category": "integrity",
                "result": "BLOCKED",
                "attack_succeeded": False,
                "policy_intervened": True,
                "policy_actions": ["quarantine"],
                "details": {"elapsed_seconds": 2.0},
            },
        ]
    }

    update_summary(report)

    summary = report["summary"]
    assert summary["normal_strict_success_rate"] == 0.0
    assert summary["normal_functional_success_rate"] == 1.0
    assert summary["normal_false_positive_rate"] == 0.0
    assert summary["attack_success_rate"] == 0.0
    assert summary["attack_policy_intervention_rate"] == 1.0
    assert summary["policy_action_counts"] == {"quarantine": 1}
