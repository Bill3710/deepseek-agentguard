"""Offline tests for fake and DeepSeek model providers."""

from types import SimpleNamespace
from typing import Any

import pytest

from agentguard.providers import (
    DeepSeekProvider,
    FakeProvider,
    ModelProvider,
    ProviderConfigurationError,
    ProviderResponseError,
)
from agentguard.schemas import ChatMessage, ProviderResponse, ToolCall
from agentguard.tools import get_tool_definitions


class StubCompletions:
    """Capture SDK arguments and return a prepared response."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self.response


def make_client(response: Any) -> tuple[Any, StubCompletions]:
    completions = StubCompletions(response)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    )
    return client, completions


def make_response(
    *,
    content: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str = "stop",
) -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model="deepseek-test")


def test_fake_provider_returns_queued_responses_and_records_calls() -> None:
    first = ProviderResponse(content="first")
    second = ProviderResponse(
        tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "a.txt"})]
    )
    provider = FakeProvider([first, second])
    messages = [ChatMessage(role="user", content="hello")]

    assert isinstance(provider, ModelProvider)
    assert provider.complete(messages).content == "first"
    assert provider.complete(messages).tool_calls[0].name == "read_file"
    assert provider.remaining_responses == 0
    assert len(provider.calls) == 2


def test_fake_provider_fails_clearly_when_queue_is_empty() -> None:
    provider = FakeProvider([])

    with pytest.raises(ProviderResponseError, match="no responses remaining"):
        provider.complete([ChatMessage(role="user", content="hello")])


def test_deepseek_provider_parses_text_without_network() -> None:
    client, completions = make_client(make_response(content="  hello  "))
    provider = DeepSeekProvider(api_key="test-key", client=client)

    result = provider.complete([ChatMessage(role="user", content="Say hello")])

    assert result.content == "hello"
    assert result.model == "deepseek-test"
    assert completions.requests[0]["model"] == "deepseek-flash"
    assert completions.requests[0]["messages"] == [
        {"role": "user", "content": "Say hello"}
    ]


def test_deepseek_provider_forwards_generated_tool_definitions() -> None:
    client, completions = make_client(make_response(content="done"))
    provider = DeepSeekProvider(api_key="test-key", client=client)
    tools = get_tool_definitions()

    provider.complete(
        [ChatMessage(role="user", content="Find an email")],
        tools=tools,
    )

    assert completions.requests[0]["tools"] == tools


def test_deepseek_provider_parses_tool_call_arguments() -> None:
    raw_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="search_emails",
            arguments='{"query":"invoice"}',
        ),
    )
    client, _ = make_client(
        make_response(tool_calls=[raw_call], finish_reason="tool_calls")
    )
    provider = DeepSeekProvider(api_key="test-key", client=client)

    result = provider.complete([ChatMessage(role="user", content="Find invoices")])

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls == [
        ToolCall(
            id="call-1",
            name="search_emails",
            arguments={"query": "invoice"},
        )
    ]


def test_deepseek_provider_rejects_invalid_tool_json() -> None:
    raw_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="read_file", arguments="not-json"),
    )
    client, _ = make_client(make_response(tool_calls=[raw_call]))
    provider = DeepSeekProvider(api_key="test-key", client=client)

    with pytest.raises(ProviderResponseError, match="invalid JSON arguments"):
        provider.complete([ChatMessage(role="user", content="Read a file")])


def test_deepseek_provider_rejects_empty_response() -> None:
    client, _ = make_client(make_response())
    provider = DeepSeekProvider(api_key="test-key", client=client)

    with pytest.raises(ProviderResponseError, match="empty response"):
        provider.complete([ChatMessage(role="user", content="hello")])


def test_deepseek_provider_requires_api_key() -> None:
    with pytest.raises(ProviderConfigurationError, match="DEEPSEEK_API_KEY"):
        DeepSeekProvider(api_key="  ")


def test_deepseek_provider_from_env_uses_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/v1/")
    monkeypatch.setenv("DEEPSEEK_MODEL", "test-model")
    client, _ = make_client(make_response(content="ok"))

    provider = DeepSeekProvider.from_env(client=client)

    assert provider.base_url == "https://example.test/v1"
    assert provider.model == "test-model"
