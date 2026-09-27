import agentguard


def test_package_import() -> None:
    assert agentguard.__version__ == "0.1.0"


def test_m2_public_api_is_exported() -> None:
    assert agentguard.ChatMessage is not None
    assert agentguard.DeepSeekProvider is not None
    assert agentguard.FakeProvider is not None
    assert agentguard.ModelProvider is not None
    assert agentguard.ProviderResponse is not None
    assert agentguard.ToolCall is not None
    assert agentguard.get_tool_definitions is not None


def test_m3_public_api_is_exported() -> None:
    assert agentguard.AgentRunner is not None
    assert agentguard.AgentRunResult is not None
    assert agentguard.AgentRunStatus is not None
    assert agentguard.AgentStep is not None
