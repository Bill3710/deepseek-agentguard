"""M5.1 public-output and audit redaction checks."""

from __future__ import annotations

from agentguard.redaction import REDACTED, Redactor


def test_redactor_removes_registered_and_key_shaped_secrets() -> None:
    redactor = Redactor(["CONFIDENTIAL-VALUE-123"])
    value = {
        "message": "value=CONFIDENTIAL-VALUE-123 key=sk-test_abcdefghijklmnop",
        "authorization": "Bearer abcdefghijklmnop",
    }

    redacted = redactor.redact(value)

    serialized = str(redacted)
    assert "CONFIDENTIAL-VALUE-123" not in serialized
    assert "sk-test_abcdefghijklmnop" not in serialized
    assert "abcdefghijklmnop" not in serialized
    assert REDACTED in serialized


def test_short_common_values_are_not_registered_as_secrets() -> None:
    redactor = Redactor(["short"])

    assert redactor.redact_text("a short status") == "a short status"

