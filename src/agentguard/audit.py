"""Append-only, redacted audit trail for protected agent runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentguard.redaction import Redactor
from agentguard.schemas import AuditEvent, AuditEventType


class AuditTrail:
    """Collect ordered security events and optionally persist them as JSONL."""

    def __init__(self, *, redactor: Redactor | None = None) -> None:
        self.redactor = redactor or Redactor()
        self._events: list[AuditEvent] = []

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        """Return an immutable view of recorded events."""
        return tuple(self._events)

    def record(
        self,
        *,
        trace_id: str,
        event_type: AuditEventType,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        policy_action: str | None = None,
        reason_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Append one event after recursively redacting its payload."""
        event = AuditEvent(
            sequence=len(self._events) + 1,
            timestamp=datetime.now(UTC),
            trace_id=trace_id,
            event_type=event_type,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            policy_action=policy_action,
            reason_code=reason_code,
            payload=self.redactor.redact(payload or {}),
        )
        self._events.append(event)
        return event

    def write_jsonl(self, path: Path) -> None:
        """Persist the current redacted trail without serializing raw secrets."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for event in self._events:
                stream.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
                stream.write("\n")
