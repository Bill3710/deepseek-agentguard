"""Tests for strict AgentGuard data models."""

import pytest
from pydantic import ValidationError

from agentguard.schemas import (
    EmailRecord,
    SearchEmailsArgs,
    SendEmailArgs,
    ToolResult,
    TrustLevel,
)


def test_email_from_alias_maps_to_sender() -> None:
    email = EmailRecord.model_validate(
        {
            "id": "email-001",
            "from": "manager@example.test",
            "subject": "Project update",
            "body": "The project is on schedule.",
            "trust_level": "untrusted",
        }
    )

    assert email.sender == "manager@example.test"
    assert email.trust_level is TrustLevel.UNTRUSTED
    assert email.model_dump(by_alias=True)["from"] == "manager@example.test"


def test_unknown_email_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EmailRecord.model_validate(
            {
                "id": "email-001",
                "from": "manager@example.test",
                "subject": "Project update",
                "body": "The project is on schedule.",
                "trust_level": "untrusted",
                "unexpected": "not allowed",
            }
        )


def test_invalid_trust_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EmailRecord.model_validate(
            {
                "id": "email-001",
                "from": "manager@example.test",
                "subject": "Project update",
                "body": "The project is on schedule.",
                "trust_level": "unknown",
            }
        )


def test_blank_search_query_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchEmailsArgs(query="   ")


def test_extra_tool_argument_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SendEmailArgs.model_validate(
            {
                "to": "recipient@example.test",
                "subject": "Hello",
                "body": "Test message",
                "cc": "unexpected@example.test",
            }
        )


def test_successful_result_cannot_contain_error() -> None:
    with pytest.raises(ValidationError):
        ToolResult(
            success=True,
            tool_name="read_file",
            output={"content": "hello"},
            error="unexpected",
        )


def test_failed_result_requires_error() -> None:
    with pytest.raises(ValidationError):
        ToolResult(success=False, tool_name="read_file")


def test_tool_result_serializes_to_json() -> None:
    result = ToolResult(
        success=True,
        tool_name="search_emails",
        output=[],
        metadata={"match_count": 0},
    )

    assert '"success":true' in result.model_dump_json()
