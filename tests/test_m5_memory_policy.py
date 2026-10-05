"""M5 namespace authorization and memory-quarantine checks."""

from __future__ import annotations

from pathlib import Path

from agentguard.providers import FakeProvider
from agentguard.schemas import ProviderResponse, ToolCall
from agentguard.secure_runner import ToolInjectionProtectedRunner
from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V33_DATA = PROJECT_ROOT / "attacks" / "data-v3.3"


def save_call(*, namespace: str = "general") -> ProviderResponse:
    """Build one deterministic memory-write proposal."""
    return ProviderResponse(
        tool_calls=[
            ToolCall(
                id="call-save",
                name="save_memory",
                arguments={
                    "content": "approved local fact",
                    "source": "user",
                    "namespace": namespace,
                },
            )
        ],
        finish_reason="tool_calls",
    )


def finish() -> ProviderResponse:
    """Build a final scripted response."""
    return ProviderResponse(content="处理完成。", finish_reason="stop")


def test_active_memory_write_requires_namespace_authorization() -> None:
    environment = SimulatedEnvironment.from_data_directory(V33_DATA)
    runner = ToolInjectionProtectedRunner(
        provider=FakeProvider([save_call(namespace="task_summary"), finish()]),
        environment=environment,
    )

    result = runner.run("保存一条本地事实。")

    blocked = result.steps[0].tool_results[0]
    assert blocked.success is False
    assert blocked.metadata["reason_code"] == (
        "MEMORY_WRITE_REQUIRES_EXPLICIT_AUTHORIZATION"
    )
    assert environment.memory == []
    assert environment.memory_candidates == []


def test_exact_namespace_authorization_allows_trusted_active_memory() -> None:
    environment = SimulatedEnvironment.from_data_directory(V33_DATA)
    runner = ToolInjectionProtectedRunner(
        provider=FakeProvider([save_call(namespace="task_summary"), finish()]),
        environment=environment,
        explicitly_authorized_memory_namespaces=frozenset({"task_summary"}),
    )

    runner.run("将这条用户提供的事实保存到 task_summary。")

    assert [item.content for item in environment.memory] == [
        "approved local fact"
    ]
    assert environment.memory[0].namespace == "task_summary"
    assert environment.memory_candidates == []


def test_namespace_authorization_does_not_expand_to_other_namespace() -> None:
    environment = SimulatedEnvironment.from_data_directory(V33_DATA)
    runner = ToolInjectionProtectedRunner(
        provider=FakeProvider([save_call(namespace="long_term"), finish()]),
        environment=environment,
        explicitly_authorized_memory_namespaces=frozenset({"task_summary"}),
    )

    result = runner.run("保存任务摘要。")

    assert result.steps[0].tool_results[0].success is False
    assert environment.memory == []


def test_tool_level_memory_authorization_cannot_bypass_namespace_check() -> None:
    environment = SimulatedEnvironment.from_data_directory(V33_DATA)
    runner = ToolInjectionProtectedRunner(
        provider=FakeProvider([save_call(), finish()]),
        environment=environment,
        explicitly_authorized_tools=frozenset({"save_memory"}),
    )

    result = runner.run("保存一条记忆。")

    assert result.steps[0].tool_results[0].success is False
    assert environment.memory == []


def test_invalid_authorized_namespace_is_rejected_at_runner_setup() -> None:
    environment = SimulatedEnvironment.from_data_directory(V33_DATA)

    try:
        ToolInjectionProtectedRunner(
            provider=FakeProvider([finish()]),
            environment=environment,
            explicitly_authorized_memory_namespaces=frozenset({"../all"}),
        )
    except ValueError as exc:
        assert str(exc) == "invalid memory namespace"
    else:
        raise AssertionError("invalid namespace should be rejected")
