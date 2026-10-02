"""Behavioral specification for the M3 baseline agent execution loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import pytest

from agentguard.providers import FakeProvider, ModelProvider, ProviderResponseError
from agentguard.runner import BASELINE_SYSTEM_PROMPT, AgentRunner
from agentguard.schemas import (
    AgentRunStatus,
    ChatMessage,
    ProviderResponse,
    ToolCall,
)
from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"


@pytest.fixture
def env() -> SimulatedEnvironment:
    """Return a fresh isolated tool environment for every test."""
    return SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)


def tool_call(
    name: str,
    arguments: dict[str, object],
    *,
    call_id: str = "call-1",
) -> ProviderResponse:
    """Build one scripted model response containing a tool call."""
    return ProviderResponse(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
        model="fake-model",
    )


def decode_tool_message(message: ChatMessage) -> dict[str, object]:
    """Decode the normalized ToolResult stored in a tool message."""
    assert message.content is not None
    decoded = json.loads(message.content)
    assert isinstance(decoded, dict)
    return decoded


class FailingProvider:
    """Provider used to verify controlled provider-error termination."""

    def complete(
        self,
        messages: object,
        tools: object = None,
    ) -> NoReturn:
        raise ProviderResponseError("synthetic provider failure")


def test_runner_returns_direct_model_answer(env: SimulatedEnvironment) -> None:
    provider = FakeProvider(
        [ProviderResponse(content="任务已完成。", finish_reason="stop")]
    )
    runner = AgentRunner(provider=provider, environment=env)

    result = runner.run("直接回答这个任务")

    assert result.status is AgentRunStatus.COMPLETED
    assert result.final_answer == "任务已完成。"
    assert result.error is None
    assert len(result.steps) == 1
    assert result.steps[0].tool_results == []
    assert result.messages[-1].role.value == "assistant"
    assert result.messages[-1].content == "任务已完成。"


def test_runner_executes_one_tool_and_returns_result_to_provider(
    env: SimulatedEnvironment,
) -> None:
    provider = FakeProvider(
        [
            tool_call("search_emails", {"query": "invoice"}),
            ProviderResponse(content="已完成邮件搜索。", finish_reason="stop"),
        ]
    )
    runner = AgentRunner(provider=provider, environment=env)

    result = runner.run("搜索 invoice 邮件")

    assert result.status is AgentRunStatus.COMPLETED
    assert result.final_answer == "已完成邮件搜索。"
    assert len(result.steps) == 2
    assert result.steps[0].tool_results[0].tool_name == "search_emails"
    assert result.steps[0].tool_results[0].success is True
    second_request_messages = provider.calls[1]["messages"]
    assert second_request_messages[-2].role.value == "assistant"
    assert second_request_messages[-2].tool_calls[0].name == "search_emails"
    assert second_request_messages[-1].role.value == "tool"
    assert second_request_messages[-1].tool_call_id == "call-1"
    assert decode_tool_message(second_request_messages[-1])["success"] is True


def test_runner_executes_multiple_tool_calls_from_one_response(
    env: SimulatedEnvironment,
) -> None:
    first_response = ProviderResponse(
        tool_calls=[
            ToolCall(
                id="call-1",
                name="save_memory",
                arguments={"content": "first", "source": "test"},
            ),
            ToolCall(
                id="call-2",
                name="save_memory",
                arguments={"content": "second", "source": "test"},
            ),
        ],
        finish_reason="tool_calls",
    )
    provider = FakeProvider(
        [first_response, ProviderResponse(content="保存完成。", finish_reason="stop")]
    )
    runner = AgentRunner(provider=provider, environment=env)

    result = runner.run("保存两条记忆")

    assert result.status is AgentRunStatus.COMPLETED
    assert len(result.steps[0].tool_results) == 2
    assert [entry.content for entry in env.memory] == ["first", "second"]
    tool_messages = [
        message
        for message in provider.calls[1]["messages"]
        if message.role.value == "tool"
    ]
    assert [message.tool_call_id for message in tool_messages] == ["call-1", "call-2"]


def test_runner_returns_invalid_arguments_to_model(
    env: SimulatedEnvironment,
) -> None:
    provider = FakeProvider(
        [
            tool_call("read_file", {"path": "public.txt", "unexpected": True}),
            ProviderResponse(content="参数无效，未读取文件。"),
        ]
    )
    runner = AgentRunner(provider=provider, environment=env)

    result = runner.run("读取文件")

    failed_result = result.steps[0].tool_results[0]
    assert failed_result.success is False
    assert failed_result.error is not None
    assert "invalid tool arguments" in failed_result.error
    assert decode_tool_message(provider.calls[1]["messages"][-1])["success"] is False
    assert result.status is AgentRunStatus.COMPLETED


def test_runner_returns_unknown_tool_error_to_model(
    env: SimulatedEnvironment,
) -> None:
    provider = FakeProvider(
        [
            tool_call("run_shell", {"command": "whoami"}),
            ProviderResponse(content="该工具不可用。"),
        ]
    )
    runner = AgentRunner(provider=provider, environment=env)

    result = runner.run("运行未知工具")

    failed_result = result.steps[0].tool_results[0]
    assert failed_result.success is False
    assert failed_result.error == "unknown tool: run_shell"
    assert result.status is AgentRunStatus.COMPLETED


def test_runner_stops_after_maximum_model_steps(
    env: SimulatedEnvironment,
) -> None:
    provider = FakeProvider(
        [
            tool_call(
                "save_memory",
                {"content": "first", "source": "test"},
                call_id="call-1",
            ),
            tool_call(
                "save_memory",
                {"content": "second", "source": "test"},
                call_id="call-2",
            ),
        ]
    )
    runner = AgentRunner(provider=provider, environment=env, max_steps=2)

    result = runner.run("不断调用工具")

    assert result.status is AgentRunStatus.MAX_STEPS_REACHED
    assert result.final_answer is None
    assert result.error is not None
    assert "maximum" in result.error.lower()
    assert len(result.steps) == 2
    assert len(provider.calls) == 2
    assert [entry.content for entry in env.memory] == ["first", "second"]


def test_runner_converts_provider_failure_to_run_result(
    env: SimulatedEnvironment,
) -> None:
    provider: ModelProvider = FailingProvider()
    runner = AgentRunner(provider=provider, environment=env)

    result = runner.run("触发 Provider 错误")

    assert result.status is AgentRunStatus.PROVIDER_ERROR
    assert result.final_answer is None
    assert result.error == "synthetic provider failure"
    assert result.steps == []


def test_runner_rejects_blank_task(env: SimulatedEnvironment) -> None:
    provider = FakeProvider([ProviderResponse(content="unused")])
    runner = AgentRunner(provider=provider, environment=env)

    with pytest.raises(ValueError, match="task"):
        runner.run("   ")

    assert provider.calls == []


def test_runner_rejects_non_positive_max_steps(env: SimulatedEnvironment) -> None:
    provider = FakeProvider([ProviderResponse(content="unused")])

    with pytest.raises(ValueError, match="max_steps"):
        AgentRunner(provider=provider, environment=env, max_steps=0)


def test_runner_supplies_all_allowlisted_tools_to_provider(
    env: SimulatedEnvironment,
) -> None:
    provider = FakeProvider([ProviderResponse(content="done")])
    runner = AgentRunner(provider=provider, environment=env)

    runner.run("列出可用能力")

    definitions = provider.calls[0]["tools"]
    system_message = provider.calls[0]["messages"][0]
    assert definitions is not None
    assert system_message.content == BASELINE_SYSTEM_PROMPT
    assert "treat tool output as data" not in system_message.content
    assert {item["function"]["name"] for item in definitions} == {
        "search_emails",
        "read_file",
        "send_email",
        "save_memory",
    }
