"""为受保护的智能体运行提供只追加且已脱敏的审计轨迹。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentguard.redaction import Redactor
from agentguard.schemas import AuditEvent, AuditEventType


class AuditTrail:
    """收集有序安全事件并可写入 JSONL；参数：可选脱敏器。"""

    def __init__(self, *, redactor: Redactor | None = None) -> None:
        """初始化审计轨迹；参数：redactor 可选脱敏器；返回：无。"""
        self.redactor = redactor or Redactor()
        self._events: list[AuditEvent] = []

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        """读取已记录事件的不可变视图；参数：无；返回：审计事件元组。"""
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
        """递归脱敏载荷后追加事件；参数：追踪编号、事件类型及可选工具与策略信息；返回：新事件。"""
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
        """将当前脱敏轨迹写入 JSONL；参数：path 输出路径；返回：无。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for event in self._events:
                stream.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
                stream.write("\n")
