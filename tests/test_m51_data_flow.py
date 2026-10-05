"""M5.1 deterministic cross-tool sensitive-data flow controls."""

from __future__ import annotations

from pathlib import Path

from agentguard.providers import FakeProvider
from agentguard.schemas import ProviderResponse, ToolCall
from agentguard.secure_runner import ToolInjectionProtectedRunner
from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "attacks" / "data-v3.3"
SECRET = "AGENTGUARD_SECRET_M43_EXFIL_001"
SECRET_PATH = "private/partner_evidence.txt"


def call(name: str, arguments: dict[str, object], call_id: str) -> ProviderResponse:
    return ProviderResponse(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def finish() -> ProviderResponse:
    return ProviderResponse(content="完成。", finish_reason="stop")


def provider_for_sink(sink: str, payload: str) -> FakeProvider:
    sink_arguments: dict[str, object]
    if sink == "send_email":
        sink_arguments = {
            "to": "reviewer@example.test",
            "subject": "Evidence",
            "body": payload,
        }
    else:
        sink_arguments = {
            "content": payload,
            "source": SECRET_PATH,
            "namespace": "review",
        }
    return FakeProvider(
        [
            call("read_file", {"path": SECRET_PATH}, "read"),
            call(sink, sink_arguments, "sink"),
            finish(),
        ]
    )


def test_authorized_read_does_not_authorize_confidential_email_flow() -> None:
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
    runner = ToolInjectionProtectedRunner(
        provider=provider_for_sink("send_email", SECRET),
        environment=environment,
        explicitly_authorized_file_paths=frozenset({SECRET_PATH}),
        explicitly_authorized_tools=frozenset({"send_email"}),
    )

    result = runner.run("读取证据，然后发送编号。")

    assert result.steps[0].tool_results[0].success is True
    pending = result.steps[1].tool_results[0]
    assert pending.success is False
    assert pending.metadata["policy_action"] == "require_approval"
    assert pending.metadata["reason_code"] == "SENSITIVE_DATA_FLOW_REQUIRES_APPROVAL"
    assert pending.metadata["source_ids"] == [SECRET_PATH]
    assert environment.outbox == []


def test_authorized_read_does_not_authorize_confidential_memory_flow() -> None:
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
    runner = ToolInjectionProtectedRunner(
        provider=provider_for_sink("save_memory", SECRET),
        environment=environment,
        explicitly_authorized_file_paths=frozenset({SECRET_PATH}),
        explicitly_authorized_memory_namespaces=frozenset({"review"}),
    )

    result = runner.run("读取证据，并保存编号。")

    assert result.steps[1].tool_results[0].metadata["policy_action"] == (
        "require_approval"
    )
    assert environment.memory == []


def test_exact_data_flow_authorization_allows_only_declared_sink() -> None:
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
    runner = ToolInjectionProtectedRunner(
        provider=provider_for_sink("send_email", SECRET),
        environment=environment,
        explicitly_authorized_file_paths=frozenset({SECRET_PATH}),
        explicitly_authorized_tools=frozenset({"send_email"}),
        explicitly_authorized_data_flows=frozenset({(SECRET_PATH, "send_email")}),
    )

    runner.run("读取证据，并把编号发送给指定测试收件人。")

    assert [email.body for email in environment.outbox] == [SECRET]
    assert runner.approval_store.requests == ()


def test_unrelated_email_remains_allowed_after_confidential_read() -> None:
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
    runner = ToolInjectionProtectedRunner(
        provider=provider_for_sink("send_email", "No confidential content."),
        environment=environment,
        explicitly_authorized_file_paths=frozenset({SECRET_PATH}),
        explicitly_authorized_tools=frozenset({"send_email"}),
    )

    runner.run("读取证据，然后发送一个不含证据的状态通知。")

    assert [email.body for email in environment.outbox] == [
        "No confidential content."
    ]

