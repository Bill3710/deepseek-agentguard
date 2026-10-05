"""Run randomized 4:1 benign-to-attack M5 online evaluation rounds."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentguard.providers import DeepSeekProvider, ProviderConfigurationError
from scripts.run_m4_attacks import (
    PROTECTION_UNTRUSTED_TOOL_OUTPUT,
    SUCCEEDED,
)
from scripts.run_m4_attacks import (
    evaluate_run as evaluate_attack_run,
)
from scripts.run_m4_attacks import (
    load_cases as load_attack_cases,
)
from scripts.run_m5_usability import (
    evaluate_run as evaluate_normal_run,
)
from scripts.run_m5_usability import (
    load_cases as load_normal_cases,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ATTACK_CASE_FILE = PROJECT_ROOT / "attacks" / "cases-v3.json"
ATTACK_DATA_DIRECTORY = PROJECT_ROOT / "attacks" / "data-v3.3"
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "m5-mixed-10-rounds-results.json"
DEFAULT_SEED = 20_261_005
ATTACK_CATEGORIES = ("prompt_injection", "confidentiality", "integrity")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse mixed-evaluation options."""
    parser = argparse.ArgumentParser(
        description="Run randomized M5 rounds with four benign tasks and one attack.",
    )
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.rounds <= 0:
        parser.error("--rounds must be greater than zero")
    return args


def load_attack_pool() -> list[dict[str, Any]]:
    """Load only the nine implemented V3 attack cases."""
    cases = load_attack_cases(ATTACK_CASE_FILE)
    selected = [case for case in cases if case["category"] in ATTACK_CATEGORIES]
    if len(selected) != 9:
        raise ValueError("mixed M5 evaluation requires nine implemented attack cases")
    return selected


def build_plan(
    normal_cases: list[dict[str, Any]],
    attack_cases: list[dict[str, Any]],
    *,
    rounds: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Build reproducible 4:1 rounds with random cases and within-round order."""
    if len(normal_cases) < 4:
        raise ValueError("mixed evaluation requires at least four normal cases")
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in attack_cases:
        by_category[case["category"]].append(case)
    missing = set(ATTACK_CATEGORIES) - by_category.keys()
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"attack pool has no cases for: {names}")

    rng = random.Random(seed)
    plan: list[dict[str, Any]] = []
    global_index = 0
    for round_number in range(1, rounds + 1):
        entries = [
            {
                "kind": "normal",
                "case_id": case["id"],
                "case_name": case["name"],
                "category": "normal",
            }
            for case in rng.sample(normal_cases, 4)
        ]
        category = rng.choice(ATTACK_CATEGORIES)
        attack_case = rng.choice(by_category[category])
        entries.append(
            {
                "kind": "attack",
                "case_id": attack_case["id"],
                "case_name": attack_case["name"],
                "category": category,
            }
        )
        rng.shuffle(entries)
        for position, entry in enumerate(entries, start=1):
            global_index += 1
            plan.append(
                {
                    "test_number": global_index,
                    "round": round_number,
                    "position": position,
                    **entry,
                }
            )
    return plan


def _policy_actions(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Return policy actions in trace order."""
    return [
        action
        for call in tool_calls
        if (action := call.get("metadata", {}).get("policy_action"))
    ]


def normalize_normal_result(
    plan_entry: dict[str, Any],
    run: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one benign result for the mixed report."""
    functional_passed = all(
        run["checks"][name]
        for name in ("status", "answer", "state", "no_unexpected_policy_block")
    )
    return {
        **plan_entry,
        "result": "PASS" if run["passed"] else "FAIL",
        "strict_passed": run["passed"],
        "functional_passed": functional_passed,
        "unexpected_policy_block": run["unexpected_policy_block"],
        "policy_actions": _policy_actions(run["tool_calls"]),
        "details": run,
    }


def normalize_attack_result(
    plan_entry: dict[str, Any],
    run: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one attack result for the mixed report."""
    policy_actions = _policy_actions(run["tool_calls"])
    return {
        **plan_entry,
        "result": run["attack_status"],
        "attack_succeeded": run["attack_status"] == SUCCEEDED,
        "defense_prevented_impact": run["attack_status"] != SUCCEEDED,
        "policy_intervened": bool(policy_actions),
        "policy_actions": policy_actions,
        "details": run,
    }


def update_summary(report: dict[str, Any]) -> None:
    """Update ratio, usability, attack, and random-distribution metrics."""
    runs = report["runs"]
    normal = [run for run in runs if run["kind"] == "normal"]
    attacks = [run for run in runs if run["kind"] == "attack"]
    strict_passed = sum(run["strict_passed"] for run in normal)
    functional_passed = sum(run["functional_passed"] for run in normal)
    false_positives = sum(run["unexpected_policy_block"] for run in normal)
    attack_successes = sum(run["attack_succeeded"] for run in attacks)
    policy_interventions = sum(run["policy_intervened"] for run in attacks)

    report["summary"] = {
        "completed_tests": len(runs),
        "normal_tests": len(normal),
        "attack_tests": len(attacks),
        "observed_ratio": f"{len(normal)}:{len(attacks)}",
        "normal_strict_passed": strict_passed,
        "normal_strict_success_rate": round(strict_passed / len(normal), 4)
        if normal
        else 0.0,
        "normal_functional_passed": functional_passed,
        "normal_functional_success_rate": round(
            functional_passed / len(normal),
            4,
        )
        if normal
        else 0.0,
        "normal_false_positive_runs": false_positives,
        "normal_false_positive_rate": round(false_positives / len(normal), 4)
        if normal
        else 0.0,
        "attack_successes": attack_successes,
        "attack_success_rate": round(attack_successes / len(attacks), 4)
        if attacks
        else 0.0,
        "attack_policy_intervention_runs": policy_interventions,
        "attack_policy_intervention_rate": round(
            policy_interventions / len(attacks),
            4,
        )
        if attacks
        else 0.0,
        "attack_status_counts": dict(Counter(run["result"] for run in attacks)),
        "attack_category_counts": dict(Counter(run["category"] for run in attacks)),
        "normal_case_counts": dict(Counter(run["case_id"] for run in normal)),
        "policy_action_counts": dict(
            Counter(action for run in runs for action in run["policy_actions"])
        ),
        "total_elapsed_seconds": round(
            sum(run["details"]["elapsed_seconds"] for run in runs),
            3,
        ),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Persist the complete plan and all finished results incrementally."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """Execute a randomized mixed M5 evaluation with DeepSeek."""
    args = parse_args(argv)
    try:
        normal_cases = load_normal_cases()
        attack_cases = load_attack_pool()
        plan = build_plan(
            normal_cases,
            attack_cases,
            rounds=args.rounds,
            seed=args.seed,
        )
        provider = DeepSeekProvider.from_env(ENV_FILE)
    except (OSError, ValueError, json.JSONDecodeError, ProviderConfigurationError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    normal_by_id = {case["id"]: case for case in normal_cases}
    attack_by_id = {case["id"]: case for case in attack_cases}
    case_occurrences: Counter[str] = Counter()
    report: dict[str, Any] = {
        "suite": "M5 DeepSeek 4:1 随机混合在线评测",
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "DeepSeek",
        "model": provider.model,
        "seed": args.seed,
        "rounds": args.rounds,
        "tests_per_round": 5,
        "normal_per_round": 4,
        "attacks_per_round": 1,
        "planned_tests": len(plan),
        "contains_real_data": False,
        "contains_api_key": False,
        "plan": plan,
        "runs": [],
        "summary": {},
    }
    output = args.output.resolve()
    write_report(output, report)

    for entry in plan:
        case_occurrences[entry["case_id"]] += 1
        occurrence = case_occurrences[entry["case_id"]]
        print(
            f"[{entry['test_number']}/{len(plan)}] round={entry['round']} "
            f"position={entry['position']} kind={entry['kind']} "
            f"case={entry['case_id']}",
            flush=True,
        )
        if entry["kind"] == "normal":
            raw = evaluate_normal_run(
                provider,
                normal_by_id[entry["case_id"]],
                occurrence,
            )
            run = normalize_normal_result(entry, raw)
        else:
            raw = evaluate_attack_run(
                provider,
                attack_by_id[entry["case_id"]],
                occurrence,
                data_directory=ATTACK_DATA_DIRECTORY,
                protection=PROTECTION_UNTRUSTED_TOOL_OUTPUT,
            )
            run = normalize_attack_result(entry, raw)
        report["runs"].append(run)
        update_summary(report)
        write_report(output, report)
        print(
            f"  result={run['result']} | actions={run['policy_actions']} | "
            f"elapsed={run['details']['elapsed_seconds']}s",
            flush=True,
        )

    report["completed_at"] = datetime.now(UTC).isoformat()
    update_summary(report)
    write_report(output, report)
    summary = report["summary"]
    print(
        f"Completed {summary['completed_tests']} tests | "
        f"normal_strict={summary['normal_strict_success_rate']:.2%} | "
        f"normal_functional={summary['normal_functional_success_rate']:.2%} | "
        f"false_positive={summary['normal_false_positive_rate']:.2%} | "
        f"attack_success={summary['attack_success_rate']:.2%}",
        flush=True,
    )
    return 1 if (
        summary["normal_functional_passed"] != summary["normal_tests"]
        or summary["attack_successes"]
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
