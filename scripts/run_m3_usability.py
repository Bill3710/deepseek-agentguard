"""Run the five M3 usability cases against DeepSeek and save public-safe results."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from agentguard.providers import DeepSeekProvider, ProviderConfigurationError
from agentguard.runner import AgentRunner
from agentguard.schemas import AgentRunResult
from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_ROOT / "tests" / "cases" / "m3_usability_cases.json"
DATA_DIRECTORY = PROJECT_ROOT / "data"
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "m3-usability-results.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse repeat count and output location."""
    parser = argparse.ArgumentParser(
        description="Run the five M3 usability cases with the real DeepSeek provider.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of online runs per case (default: 3).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON report path.",
    )
    args = parser.parse_args(argv)
    if args.repeats <= 0:
        parser.error("--repeats must be greater than zero")
    return args


def load_cases() -> list[dict[str, Any]]:
    """Load the validated public M3 case definitions."""
    with CASE_FILE.open(encoding="utf-8") as stream:
        cases = json.load(stream)
    if not isinstance(cases, list) or len(cases) != 5:
        raise ValueError("M3 usability suite must contain exactly five cases")
    return cases


def flatten_tool_calls(result: AgentRunResult) -> list[dict[str, Any]]:
    """Create a public-safe trace without credentials or request headers."""
    trace = []
    for step in result.steps:
        for tool_call, tool_result in zip(
            step.model_response.tool_calls,
            step.tool_results,
            strict=True,
        ):
            trace.append(
                {
                    "step": step.step_number,
                    "call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "success": tool_result.success,
                    "error": tool_result.error,
                }
            )
    return trace


def snapshot_state(environment: SimulatedEnvironment) -> dict[str, Any]:
    """Capture only synthetic mutable state needed for acceptance checks."""
    return {
        "memory_count": len(environment.memory),
        "memory": [entry.model_dump(mode="json") for entry in environment.memory],
        "outbox_count": len(environment.outbox),
        "outbox": [email.model_dump(mode="json") for email in environment.outbox],
    }


def check_expected_state(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> bool:
    """Check exact state requirements for memory and outbox cases."""
    if not expected:
        return True
    if "memory_count" in expected and expected["memory_count"] != actual["memory_count"]:
        return False
    if "memory_content" in expected:
        if not actual["memory"]:
            return False
        latest_memory = actual["memory"][-1]
        if latest_memory["content"] != expected["memory_content"]:
            return False
        if latest_memory["source"] != expected["memory_source"]:
            return False
    if "outbox_count" in expected and expected["outbox_count"] != actual["outbox_count"]:
        return False
    if "recipient" in expected:
        if not actual["outbox"]:
            return False
        latest_email = actual["outbox"][-1]
        for field in ("recipient", "subject", "body"):
            actual_field = "to" if field == "recipient" else field
            if latest_email[actual_field] != expected[field]:
                return False
    return True


def check_expected_facts(expected: dict[str, Any], answer: str | None) -> bool:
    """Apply small deterministic checks to facts grounded in synthetic data."""
    if not answer:
        return False
    normalized = answer.casefold()
    if "answer" in expected:
        return re.search(rf"(?<!\d){re.escape(expected['answer'])}(?!\d)", answer) is not None
    if "project" in expected and expected["project"].casefold() not in normalized:
        return False
    if "status" in expected:
        status_phrases = {
            expected["status"].casefold(),
            "按计划",
            "进展顺利",
            "正常进行",
        }
        if not any(phrase in normalized for phrase in status_phrases):
            return False
    return True


def evaluate_run(
    provider: DeepSeekProvider,
    case: dict[str, Any],
    run_number: int,
) -> dict[str, Any]:
    """Run one online case in a fresh synthetic environment."""
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
    runner = AgentRunner(provider=provider, environment=environment)
    started = perf_counter()
    result = runner.run(case["task"])
    elapsed_seconds = round(perf_counter() - started, 3)

    trace = flatten_tool_calls(result)
    actual_tools = [item["name"] for item in trace]
    state = snapshot_state(environment)
    checks = {
        "status": result.status.value == case["expected_status"],
        "tool_sequence": actual_tools == case["expected_tools"],
        "all_tools_succeeded": all(item["success"] for item in trace),
        "expected_facts": check_expected_facts(
            case["expected_facts"],
            result.final_answer,
        ),
        "expected_state": check_expected_state(case["expected_state"], state),
    }

    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "run_number": run_number,
        "task": case["task"],
        "status": result.status.value,
        "error": result.error,
        "elapsed_seconds": elapsed_seconds,
        "model_steps": len(result.steps),
        "tool_calls": trace,
        "final_answer": result.final_answer,
        "synthetic_state": state,
        "checks": checks,
        "passed": all(checks.values()),
    }


def update_summary(report: dict[str, Any]) -> None:
    """Refresh aggregate counts after each completed online run."""
    runs = report["runs"]
    passed = sum(1 for run in runs if run["passed"])
    report["summary"] = {
        "completed_runs": len(runs),
        "passed_runs": passed,
        "failed_runs": len(runs) - passed,
        "pass_rate": round(passed / len(runs), 4) if runs else 0.0,
        "total_elapsed_seconds": round(
            sum(run["elapsed_seconds"] for run in runs),
            3,
        ),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Persist progress after every run so partial results survive interruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """Execute all cases repeatedly and save an aggregate JSON report."""
    args = parse_args(argv)
    cases = load_cases()
    try:
        provider = DeepSeekProvider.from_env(ENV_FILE)
    except ProviderConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "suite": "M3 在线可用性测试",
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "DeepSeek",
        "model": provider.model,
        "case_file": str(CASE_FILE.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "case_count": len(cases),
        "repeats_per_case": args.repeats,
        "planned_runs": len(cases) * args.repeats,
        "contains_api_key": False,
        "runs": [],
        "summary": {},
    }
    output = args.output.resolve()

    for case in cases:
        for run_number in range(1, args.repeats + 1):
            current = len(report["runs"]) + 1
            print(
                f"[{current}/{report['planned_runs']}] "
                f"{case['id']} run {run_number}",
                flush=True,
            )
            run = evaluate_run(provider, case, run_number)
            report["runs"].append(run)
            update_summary(report)
            write_report(output, report)
            outcome = "PASS" if run["passed"] else "FAIL"
            tools = [item["name"] for item in run["tool_calls"]]
            print(
                f"  {outcome} | status={run['status']} | tools={tools} | "
                f"elapsed={run['elapsed_seconds']}s",
                flush=True,
            )

    report["completed_at"] = datetime.now(UTC).isoformat()
    update_summary(report)
    write_report(output, report)
    summary = report["summary"]
    try:
        display_output = output.relative_to(PROJECT_ROOT)
    except ValueError:
        display_output = Path(output.name)
    print(
        f"Completed: {summary['passed_runs']}/{summary['completed_runs']} passed; "
        f"report: {display_output.as_posix()}",
        flush=True,
    )
    return 0 if summary["failed_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
