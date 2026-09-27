"""Tests for deterministic local simulated tools."""

from pathlib import Path

import pytest

from agentguard.schemas import (
    ReadFileArgs,
    SaveMemoryArgs,
    SearchEmailsArgs,
    SendEmailArgs,
)
from agentguard.tools import (
    TOOL_ARGUMENT_MODELS,
    TOOL_REGISTRY,
    SimulatedEnvironment,
    execute_tool,
    get_tool_definitions,
    read_file,
    save_memory,
    search_emails,
    send_email,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"


@pytest.fixture
def env() -> SimulatedEnvironment:
    return SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)


def test_environment_loads_synthetic_data(env: SimulatedEnvironment) -> None:
    assert len(env.emails) == 1
    assert "public/project_status.txt" in env.files
    assert "private/confidential.txt" in env.files
    assert env.outbox == []
    assert env.memory == []


def test_search_emails_is_case_insensitive(env: SimulatedEnvironment) -> None:
    result = search_emails(env, SearchEmailsArgs(query="PROJECT ALPHA"))

    assert result.success is True
    assert result.metadata["match_count"] == 1
    assert result.output[0]["id"] == "email-001"


def test_search_emails_returns_empty_list_for_no_match(env: SimulatedEnvironment) -> None:
    result = search_emails(env, SearchEmailsArgs(query="does-not-exist"))

    assert result.success is True
    assert result.output == []
    assert result.metadata["match_count"] == 0


def test_read_public_file_preserves_classification(env: SimulatedEnvironment) -> None:
    result = read_file(env, ReadFileArgs(path="public/project_status.txt"))

    assert result.success is True
    assert result.output["classification"] == "public"


def test_read_confidential_file_preserves_classification(env: SimulatedEnvironment) -> None:
    result = read_file(env, ReadFileArgs(path="private/confidential.txt"))

    assert result.success is True
    assert result.output["classification"] == "confidential"


@pytest.mark.parametrize(
    "unsafe_path",
    ["../secret.txt", "public/../secret.txt", "C:\\secret.txt", "/etc/passwd"],
)
def test_read_file_rejects_unsafe_paths(
    env: SimulatedEnvironment,
    unsafe_path: str,
) -> None:
    result = read_file(env, ReadFileArgs(path=unsafe_path))

    assert result.success is False
    assert result.error is not None


def test_read_file_reports_missing_synthetic_file(env: SimulatedEnvironment) -> None:
    result = read_file(env, ReadFileArgs(path="public/missing.txt"))

    assert result.success is False
    assert result.error == "simulated file not found: public/missing.txt"


def test_send_email_only_appends_to_local_outbox(env: SimulatedEnvironment) -> None:
    result = send_email(
        env,
        SendEmailArgs(
            to="recipient@example.test",
            subject="Test",
            body="Synthetic message",
        ),
    )

    assert result.success is True
    assert result.metadata["simulated"] is True
    assert len(env.outbox) == 1
    assert env.outbox[0].id == "outbox-001"


def test_send_email_rejects_non_reserved_domain(env: SimulatedEnvironment) -> None:
    result = send_email(
        env,
        SendEmailArgs(
            to="recipient@real-domain.invalid",
            subject="Test",
            body="Synthetic message",
        ),
    )

    assert result.success is False
    assert env.outbox == []


def test_save_memory_only_changes_local_state(env: SimulatedEnvironment) -> None:
    result = save_memory(
        env,
        SaveMemoryArgs(content="Synthetic fact", source="email-001"),
    )

    assert result.success is True
    assert len(env.memory) == 1
    assert env.memory[0].id == "memory-001"


def test_execute_tool_rejects_unknown_tool(env: SimulatedEnvironment) -> None:
    result = execute_tool(env, "run_shell", {"command": "whoami"})

    assert result.success is False
    assert result.error == "unknown tool: run_shell"


def test_execute_tool_rejects_invalid_arguments(env: SimulatedEnvironment) -> None:
    result = execute_tool(
        env,
        "send_email",
        {
            "to": "recipient@example.test",
            "subject": "Test",
            "body": "Synthetic message",
            "unexpected": "blocked",
        },
    )

    assert result.success is False
    assert "invalid tool arguments" in result.error
    assert env.outbox == []


def test_environments_do_not_share_mutable_state() -> None:
    first = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
    second = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)

    send_email(
        first,
        SendEmailArgs(
            to="recipient@example.test",
            subject="Test",
            body="Synthetic message",
        ),
    )

    assert len(first.outbox) == 1
    assert second.outbox == []


def test_tool_definitions_match_allowlisted_tools() -> None:
    definitions = get_tool_definitions()

    assert {item["function"]["name"] for item in definitions} == set(TOOL_REGISTRY)
    assert set(TOOL_ARGUMENT_MODELS) == set(TOOL_REGISTRY)
    for item in definitions:
        function = item["function"]
        parameters = function["parameters"]
        assert item["type"] == "function"
        assert function["description"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False


def test_tool_definitions_are_fresh_copies() -> None:
    first = get_tool_definitions()
    first[0]["function"]["name"] = "tampered"

    second = get_tool_definitions()

    assert second[0]["function"]["name"] == "search_emails"
