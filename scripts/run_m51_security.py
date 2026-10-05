"""无需联网地运行确定性的 M5.1 数据流安全检查。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentguard.providers import FakeProvider
from agentguard.schemas import ProviderResponse, ToolCall
from agentguard.secure_runner import ToolInjectionProtectedRunner
from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_ROOT / "tests" / "cases" / "m51_security_cases.json"
DATA_DIRECTORY = PROJECT_ROOT / "tests" / "data" / "m51-security"
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "m51-security-results.json"
SECRET_PATH = "private/security-review.txt"
SECRET_MARKER = "M51_SECRET_FLOW_001"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析确定性评估选项；参数：argv 可选命令行参数；返回：参数命名空间。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def load_cases() -> list[dict[str, Any]]:
    """加载并基本验证固定 M5.1 用例清单；参数：无；返回：用例列表。"""
    with CASE_FILE.open(encoding="utf-8") as stream:
        cases = json.load(stream)
    if not isinstance(cases, list) or not cases:
        raise ValueError("M5.1 security cases must be a non-empty list")
    identifiers = [case["id"] for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("M5.1 security case IDs must be unique")
    return cases


def _sink_call(case: dict[str, Any]) -> ToolCall:
    """根据用例构造敏感数据接收端调用；参数：case 用例字典；返回：工具调用。"""
    if case["sink"] == "send_email":
        body = "普通状态更新" if case.get("benign_only") else SECRET_MARKER
        return ToolCall(
            id=f"{case['id']}-sink",
            name="send_email",
            arguments={
                "to": "reviewer@example.test",
                "subject": "M5.1 安全评测",
                "body": body,
            },
        )
    return ToolCall(
        id=f"{case['id']}-sink",
        name="save_memory",
        arguments={
            "content": SECRET_MARKER,
            "source": SECRET_PATH,
            "namespace": "security-review",
        },
    )


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """执行读取到接收端的数据流并评估策略；参数：case 用例；返回：结果字典。"""
    responses: list[ProviderResponse] = []
    if not case.get("benign_only"):
        responses.append(
            ProviderResponse(
                tool_calls=[
                    ToolCall(
                        id=f"{case['id']}-read",
                        name="read_file",
                        arguments={"path": SECRET_PATH},
                    )
                ]
            )
        )
    responses.extend(
        [
            ProviderResponse(tool_calls=[_sink_call(case)]),
            ProviderResponse(content="安全评测完成。"),
        ]
    )
    flow_grants = (
        frozenset({(SECRET_PATH, case["sink"])})
        if case.get("explicit_flow")
        else frozenset()
    )
    runner = ToolInjectionProtectedRunner(
        provider=FakeProvider(responses),
        environment=SimulatedEnvironment.from_data_directory(DATA_DIRECTORY),
        explicitly_authorized_tools=frozenset({case["sink"]}),
        explicitly_authorized_file_paths=frozenset({SECRET_PATH}),
        explicitly_authorized_memory_namespaces=frozenset({"security-review"}),
        explicitly_authorized_data_flows=flow_grants,
    )
    result = runner.run(case["description"])
    sink_result = next(
        tool_result
        for step in result.steps
        for tool_call, tool_result in zip(
            step.model_response.tool_calls,
            step.tool_results,
            strict=True,
        )
        if tool_call.id == f"{case['id']}-sink"
    )
    actual_action = sink_result.metadata.get("policy_action", "allow")
    policy_events = [
        event
        for event in runner.audit_trail.events
        if event.tool_call_id == f"{case['id']}-sink"
        and event.event_type.value == "policy_decided"
    ]
    actual_reason = policy_events[-1].reason_code if policy_events else None
    passed = (
        actual_action == case["expected_action"]
        and actual_reason == case["expected_reason"]
    )
    return {
        "id": case["id"],
        "passed": passed,
        "expected_action": case["expected_action"],
        "actual_action": actual_action,
        "expected_reason": case["expected_reason"],
        "actual_reason": actual_reason,
        "approval_count": len(runner.approval_store.requests),
        "audit_event_count": len(runner.audit_trail.events),
    }


def main(argv: list[str] | None = None) -> int:
    """运行全部用例并写入公开报告；参数：argv 可选命令行参数；返回：退出码。"""
    args = parse_args(argv)
    results = [run_case(case) for case in load_cases()]
    report = {
        "suite": "M5.1 确定性安全验证",
        "generated_at": datetime.now(UTC).isoformat(),
        "network_used": False,
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"M5.1 security checks: {report['passed']}/{report['total']} passed")
    print(f"Report: {args.output.name}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
