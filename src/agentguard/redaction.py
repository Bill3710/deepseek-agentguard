"""为日志和公开评估产物提供确定性的敏感信息脱敏。"""

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
    """脱敏指定值、凭据形态字符串和敏感字段；参数：secrets 初始秘密值序列。"""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        """初始化脱敏器并登记秘密值；参数：secrets 待保护字符串序列；返回：无。"""
        self._secrets: set[str] = set()
        for secret in secrets:
            self.add_secret(secret)

    def add_secret(self, secret: str) -> None:
        """登记后续需精确替换的秘密值；参数：secret 长度至少为八的字符串；返回：无。"""
        if isinstance(secret, str) and len(secret.strip()) >= 8:
            self._secrets.add(secret)

    def redact_text(self, value: str) -> str:
        """脱敏文本中的登记值及常见凭据形态；参数：value 原文本；返回：脱敏文本。"""
        redacted = value
        for secret in sorted(self._secrets, key=len, reverse=True):
            redacted = redacted.replace(secret, REDACTED)
        return KEY_SHAPED_SECRET.sub(REDACTED, redacted)

    def redact(self, value: Any, *, key: str | None = None) -> Any:
        """递归生成可转为 JSON 的脱敏副本；参数：value 任意值、key 可选字段名；返回：脱敏值。"""
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

