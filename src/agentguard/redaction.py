"""Deterministic redaction for logs and public evaluation artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    }
)
KEY_SHAPED_SECRET = re.compile(
    r"(?i)\b(?:sk|api)[-_][A-Za-z0-9_-]{12,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b"
)


class Redactor:
    """Redact configured values, credential-shaped strings, and sensitive fields."""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        self._secrets: set[str] = set()
        for secret in secrets:
            self.add_secret(secret)

    def add_secret(self, secret: str) -> None:
        """Register a non-trivial exact value for later redaction."""
        if isinstance(secret, str) and len(secret.strip()) >= 8:
            self._secrets.add(secret)

    def redact_text(self, value: str) -> str:
        """Redact registered values and common credential shapes from text."""
        redacted = value
        for secret in sorted(self._secrets, key=len, reverse=True):
            redacted = redacted.replace(secret, REDACTED)
        return KEY_SHAPED_SECRET.sub(REDACTED, redacted)

    def redact(self, value: Any, *, key: str | None = None) -> Any:
        """Recursively create a JSON-compatible redacted copy."""
        if key is not None and key.casefold() in SENSITIVE_KEYS:
            return REDACTED
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return {
                str(item_key): self.redact(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, tuple | list):
            return [self.redact(item) for item in value]
        return value

