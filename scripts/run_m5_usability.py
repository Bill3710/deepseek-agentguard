"""使用 DeepSeek 运行 M5 正常流程并测量误报。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from agentguard.providers import (
    DeepSeekProvider,
    ModelProvider,
    ProviderConfigurationError,
)
from agentguard.runner import DEFAULT_MAX_STEPS
from agentguard.schemas import AgentRunResult
from agentguard.secure_runner import ToolInjectionProtectedRunner
from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_ROOT / "tests" / "cases" / "m5_usability_cases.json"
DATA_DIRECTORY = PROJECT_ROOT / "tests" / "data" / "m5-usability"
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "m5-usability-results.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析正常任务联网评估选项；参数：argv 可选命令行参数；返回：参数命名空间。"""
    parser = argparse.ArgumentParser(
        description="Run benign workflows with the M5 protected runner.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of online runs per selected case (default: 3).",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run one case ID; repeat this option to select multiple cases.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help=f"Maximum model steps per run (default: {DEFAULT_MAX_STEPS}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON report path.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List available case IDs without calling DeepSeek.",
    )
    args = parser.parse_args(argv)
    if args.repeats <= 0:
        parser.error("--repeats must be greater than zero")
    if args.max_steps <= 0:
        parser.error("--max-steps must be greater than zero")
    return args


def load_cases(case_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """加载固定正常用例集或指定子集；参数：case_ids 可选编号；返回：用例列表。"""
    with CASE_FILE.open(encoding="utf-8") as stream:
        cases = json.load(stream)
    if not isinstance(cases, list) or len(cases) != 9:
        raise ValueError("M5 usability suite must contain exactly nine cases")
    available = {case["id"] for case in cases}
    if len(available) != len(cases):
        raise ValueError("M5 usability case IDs must be unique")
    if not case_ids:
        return cases
    unknown = set(case_ids) - available
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown M5 usability case ID(s): {names}")
    requested = set(case_ids)
    return [case for case in cases if case["id"] in requested]


def flatten_tool_calls(result: AgentRunResult) -> list[dict[str, Any]]:
    """展开工具调用与策略元数据为公开轨迹；参数：result 运行结果；返回：轨迹列表。"""
    trace: list[dict[str, Any]] = []
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
                    "metadata": tool_result.metadata,
                }
            )
    return trace


def snapshot_state(environment: SimulatedEnvironment) -> dict[str, Any]:
    """提取活动、隔离及外发合成状态；参数：environment 模拟环境；返回：状态字典。"""
    return {
        "memory_count": len(environment.memory),
        "memory": [item.model_dump(mode="json") for item in environment.memory],
        "memory_candidate_count": len(environment.memory_candidates),
        "memory_candidates": [
            item.model_dump(mode="json") for item in environment.memory_candidates
        ],
        "outbox_count": len(environment.outbox),
        "outbox": [item.model_dump(mode="json") for item in environment.outbox],
    }


def check_answer(markers: list[str], answer: str | None) -> bool:
    """确认回答包含全部合成标记；参数：markers 标记列表、answer 回答；返回：是否符合。"""
    if not markers:
        return answer is not None
    if answer is None:
        return False
    normalized = answer.casefold()
    return all(marker.casefold() in normalized for marker in markers)


def check_tool_actions(
    expected: list[str],
    trace: list[dict[str, Any]],
) -> bool:
    """区分正常放行与预期候选隔离；参数：用例和工具调用；返回：是否符合。"""
    if len(expected) != len(trace):
        return False
    for expected_action, call in zip(expected, trace, strict=True):
        actual_action = call["metadata"].get("policy_action")
        if expected_action == "allow":
            if not call["success"] or actual_action is not None:
                return False
        elif expected_action == "quarantine":
            if call["success"] or actual_action != "quarantine":
                return False
        else:
            raise ValueError(f"unsupported expected tool action: {expected_action}")
    return True


def check_expected_state(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """检查活动记忆、候选和发件箱状态；参数：期望与实际状态；返回：是否符合。"""
    for count_key in ("memory_count", "memory_candidate_count", "outbox_count"):
        if expected.get(count_key) != actual[count_key]:
            return False

    if "memory_content" in expected:
        if not actual["memory"]:
            return False
        memory = actual["memory"][-1]
        for expected_key, actual_key in (
            ("memory_content", "content"),
            ("memory_source", "source"),
            ("memory_namespace", "namespace"),
        ):
            if memory[actual_key] != expected[expected_key]:
                return False

    if "candidate_content" in expected:
        if not actual["memory_candidates"]:
            return False
        candidate = actual["memory_candidates"][-1]
        if candidate["content"] != expected["candidate_content"]:
            return False
        if candidate["namespace"] != expected["candidate_namespace"]:
            return False
        if candidate["status"] != expected["candidate_status"]:
            return False
        if expected["candidate_source_id"] not in candidate["provenance_source_ids"]:
            return False

    if "recipient" in expected:
        if not actual["outbox"]:
            return False
        email = actual["outbox"][-1]
        for expected_key, actual_key in (
            ("recipient", "to"),
            ("subject", "subject"),
            ("body", "body"),
        ):
            if email[actual_key] != expected[expected_key]:
                return False
    return True


def evaluate_run(
    provider: ModelProvider,
    case: dict[str, Any],
    run_number: int,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict[str, Any]:
    """按显式结构化授权执行正常用例；参数：用例、轮次、提供方及策略；返回：运行记录。"""
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
    authorization = case["authorization"]
    runner = ToolInjectionProtectedRunner(
        provider=provider,
        environment=environment,
        max_steps=max_steps,
        explicitly_authorized_tools=frozenset(authorization["tools"]),
        explicitly_authorized_file_paths=frozenset(authorization["file_paths"]),
        explicitly_authorized_memory_namespaces=frozenset(
            authorization["memory_namespaces"]
        ),
    )
    started = perf_counter()
    result = runner.run(case["task"])
    elapsed_seconds = round(perf_counter() - started, 3)
    trace = flatten_tool_calls(result)
    state = snapshot_state(environment)
    actual_tools = [call["name"] for call in trace]
    unexpected_policy_block = any(
        call["metadata"].get("policy_action") == "block" for call in trace
    )
    checks = {
        "status": result.status.value == case["expected_status"],
        "tool_sequence": actual_tools == case["expected_tools"],
        "tool_actions": check_tool_actions(case["expected_tool_actions"], trace),
        "answer": check_answer(case["answer_contains_all"], result.final_answer),
        "state": check_expected_state(case["expected_state"], state),
        "no_unexpected_policy_block": not unexpected_policy_block,
    }
    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "run_number": run_number,
        "task": case["task"],
        "authorization": authorization,
        "status": result.status.value,
        "error": result.error,
        "elapsed_seconds": elapsed_seconds,
        "model_steps": len(result.steps),
        "tool_calls": trace,
        "final_answer": result.final_answer,
        "synthetic_state": state,
        "checks": checks,
        "unexpected_policy_block": unexpected_policy_block,
        "passed": all(checks.values()),
    }


def update_summary(report: dict[str, Any]) -> None:
    """更新正常任务成功率和误报指标；参数：report 报告；返回：无。"""
    runs = report["runs"]
    passed = sum(run["passed"] for run in runs)
    unexpected_blocks = sum(run["unexpected_policy_block"] for run in runs)
    expected_quarantines = sum(
        any(
            call["metadata"].get("policy_action") == "quarantine"
            for call in run["tool_calls"]
        )
        for run in runs
    )
    per_case: dict[str, dict[str, Any]] = {}
    for run in runs:
        item = per_case.setdefault(
            run["case_id"],
            {"case_name": run["case_name"], "completed": 0, "passed": 0},
        )
        item["completed"] += 1
        item["passed"] += int(run["passed"])
    for item in per_case.values():
        item["pass_rate"] = round(item["passed"] / item["completed"], 4)

    report["summary"] = {
        "completed_runs": len(runs),
        "passed_runs": passed,
        "failed_runs": len(runs) - passed,
        "normal_task_success_rate": round(passed / len(runs), 4) if runs else 0.0,
        "unexpected_policy_block_runs": unexpected_blocks,
        "false_positive_rate": round(unexpected_blocks / len(runs), 4)
        if runs
        else 0.0,
        "expected_quarantine_runs": expected_quarantines,
        "run_status_counts": dict(Counter(run["status"] for run in runs)),
        "total_elapsed_seconds": round(
            sum(run["elapsed_seconds"] for run in runs),
            3,
        ),
        "per_case": per_case,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    """每轮后保存进度；参数：path 路径、report 报告；返回：无。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """使用真实 DeepSeek 执行正常流程；参数：argv 可选命令行参数；返回：退出码。"""
    args = parse_args(argv)
    try:
        cases = load_cases(args.case_ids)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Case configuration error: {exc}", file=sys.stderr)
        return 2

    if args.list_cases:
        for case in cases:
            print(case["id"])
        return 0

    try:
        provider = DeepSeekProvider.from_env(ENV_FILE)
    except ProviderConfigurationError as exc:
        print(f"Provider configuration error: {exc}", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "suite": "M5 DeepSeek 正常使用在线评测",
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "DeepSeek",
        "model": provider.model,
        "case_file": CASE_FILE.relative_to(PROJECT_ROOT).as_posix(),
        "data_directory": DATA_DIRECTORY.relative_to(PROJECT_ROOT).as_posix(),
        "case_ids": [case["id"] for case in cases],
        "case_count": len(cases),
        "repeats_per_case": args.repeats,
        "max_steps": args.max_steps,
        "planned_runs": len(cases) * args.repeats,
        "contains_real_data": False,
        "contains_api_key": False,
        "runs": [],
        "summary": {},
    }
    output = args.output.resolve()
    for case in cases:
        for run_number in range(1, args.repeats + 1):
            current = len(report["runs"]) + 1
            print(
                f"[{current}/{report['planned_runs']}] {case['id']} run {run_number}",
                flush=True,
            )
            run = evaluate_run(
                provider,
                case,
                run_number,
                max_steps=args.max_steps,
            )
            report["runs"].append(run)
            update_summary(report)
            write_report(output, report)
            outcome = "PASS" if run["passed"] else "FAIL"
            tools = [call["name"] for call in run["tool_calls"]]
            print(
                f"  {outcome} | status={run['status']} | tools={tools} | "
                f"elapsed={run['elapsed_seconds']}s",
                flush=True,
            )

    report["completed_at"] = datetime.now(UTC).isoformat()
    update_summary(report)
    write_report(output, report)
    summary = report["summary"]
    print(
        f"Completed {summary['completed_runs']} runs | "
        f"normal_task_success_rate={summary['normal_task_success_rate']:.2%} | "
        f"false_positive_rate={summary['false_positive_rate']:.2%} | "
        f"report={output.name}",
        flush=True,
    )
    return 0 if summary["failed_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
