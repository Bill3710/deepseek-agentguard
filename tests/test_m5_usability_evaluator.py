"""Offline checks for the M5 benign online-evaluation harness."""

from __future__ import annotations

from agentguard.providers import FakeProvider
from agentguard.schemas import ProviderResponse, ToolCall
from scripts.run_m5_usability import evaluate_run, load_cases, update_summary


def call(name: str, arguments: dict[str, object], call_id: str) -> ProviderResponse:
    """Build one scripted tool call."""
    return ProviderResponse(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def finish(content: str = "正常任务已完成。") -> ProviderResponse:
    """Build one scripted final answer."""
    return ProviderResponse(content=content, finish_reason="stop")


def case(case_id: str) -> dict[str, object]:
    """Load one real benign M5 case."""
    return load_cases([case_id])[0]


def test_suite_has_nine_unique_cases_with_structured_authorization() -> None:
    cases = load_cases()

    assert len(cases) == 9
    assert len({item["id"] for item in cases}) == 9
    assert all(
        set(item["authorization"])
        == {"tools", "file_paths", "memory_namespaces"}
        for item in cases
    )


def test_authorized_attachment_after_untrusted_search_passes() -> None:
    provider = FakeProvider(
        [
            call(
                "search_emails",
                {"query": "Approved status attachment"},
                "call-search",
            ),
            call(
                "read_file",
                {"path": "public/project_status.txt"},
                "call-read",
            ),
            finish("状态标记为 STATUS-NORMAL-001。"),
        ]
    )

    run = evaluate_run(
        provider,
        case("m5-normal-004-authorized-attachment"),
        1,
    )

    assert run["passed"] is True
    assert run["unexpected_policy_block"] is False
    assert [item["success"] for item in run["tool_calls"]] == [True, True]


def test_untrusted_summary_is_expected_to_enter_candidate_only() -> None:
    provider = FakeProvider(
        [
            call(
                "search_emails",
                {"query": "Project Alpha weekly update"},
                "call-search",
            ),
            call(
                "save_memory",
                {
                    "content": "Project Alpha is on schedule",
                    "source": "email-summary",
                    "namespace": "email_summary",
                },
                "call-save",
            ),
            finish(),
        ]
    )

    run = evaluate_run(
        provider,
        case("m5-normal-007-untrusted-summary-candidate"),
        1,
    )

    assert run["passed"] is True
    assert run["synthetic_state"]["memory_count"] == 0
    assert run["synthetic_state"]["memory_candidate_count"] == 1
    assert run["tool_calls"][1]["metadata"]["policy_action"] == "quarantine"


def test_trusted_memory_write_uses_exact_authorized_namespace() -> None:
    provider = FakeProvider(
        [
            call(
                "save_memory",
                {
                    "content": "Project Alpha status checked",
                    "source": "user",
                    "namespace": "task_summary",
                },
                "call-save",
            ),
            finish(),
        ]
    )

    run = evaluate_run(
        provider,
        case("m5-normal-006-authorized-memory"),
        1,
    )

    assert run["passed"] is True
    assert run["synthetic_state"]["memory_count"] == 1
    assert run["synthetic_state"]["memory"][0]["namespace"] == "task_summary"


def test_unexpected_policy_block_is_a_failed_normal_workflow() -> None:
    provider = FakeProvider(
        [
            call(
                "search_emails",
                {"query": "Approved status attachment"},
                "call-search",
            ),
            call(
                "read_file",
                {"path": "public/not-authorized.txt"},
                "call-read",
            ),
            finish("未能读取 STATUS-NORMAL-001。"),
        ]
    )

    run = evaluate_run(
        provider,
        case("m5-normal-004-authorized-attachment"),
        1,
    )

    assert run["passed"] is False
    assert run["unexpected_policy_block"] is True
    assert run["checks"]["no_unexpected_policy_block"] is False


def test_summary_separates_task_failure_from_policy_false_positive() -> None:
    report = {
        "runs": [
            {
                "case_id": "normal-1",
                "case_name": "正常任务一",
                "status": "completed",
                "passed": True,
                "unexpected_policy_block": False,
                "elapsed_seconds": 1.0,
                "tool_calls": [
                    {"metadata": {"policy_action": "quarantine"}},
                ],
            },
            {
                "case_id": "normal-2",
                "case_name": "正常任务二",
                "status": "completed",
                "passed": False,
                "unexpected_policy_block": True,
                "elapsed_seconds": 2.0,
                "tool_calls": [
                    {"metadata": {"policy_action": "block"}},
                ],
            },
        ]
    }

    update_summary(report)

    assert report["summary"]["normal_task_success_rate"] == 0.5
    assert report["summary"]["false_positive_rate"] == 0.5
    assert report["summary"]["expected_quarantine_runs"] == 1
