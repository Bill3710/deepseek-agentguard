"""为高风险模拟工具调用提供精确绑定、限时且仅可使用一次的审批机制。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from agentguard.schemas import ApprovalRequest, ApprovalStatus, ToolCall


def tool_call_hash(tool_call: ToolCall) -> str:
    """计算绑定工具名称与全部参数的稳定哈希；参数：tool_call 工具调用；返回：SHA-256 十六进制摘要。"""
    canonical = json.dumps(
        {"name": tool_call.name, "arguments": tool_call.arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalStore:
    """管理待审批请求且不自动执行工具；参数：无；内部保存请求集合与递增编号。"""

    def __init__(self) -> None:
        """初始化空审批存储；参数：无；返回：无。"""
        self._requests: dict[str, ApprovalRequest] = {}
        self._next_id = 1

    @property
    def requests(self) -> tuple[ApprovalRequest, ...]:
        """按创建顺序读取全部审批记录；参数：无；返回：不可变审批记录元组。"""
        return tuple(self._requests.values())

    def create(
        self,
        tool_call: ToolCall,
        *,
        reason_code: str,
        source_ids: tuple[str, ...] = (),
        ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """为指定调用创建待审批记录；参数：工具调用、原因码、来源、有效期和当前时间；返回：审批请求。"""
        if ttl_seconds <= 0:
            raise ValueError("approval ttl_seconds must be greater than zero")
        created_at = now or datetime.now(UTC)
        request = ApprovalRequest(
            id=f"approval-{self._next_id:03d}",
            tool_call=tool_call.model_copy(deep=True),
            argument_hash=tool_call_hash(tool_call),
            reason_code=reason_code,
            source_ids=list(source_ids),
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=ttl_seconds),
        )
        self._next_id += 1
        self._requests[request.id] = request
        return request

    def get(self, approval_id: str) -> ApprovalRequest:
        """按编号读取审批；参数：approval_id 审批编号；返回：审批请求；异常：编号未知时抛出 ValueError。"""
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise ValueError(f"unknown approval: {approval_id}") from exc

    def approve(self, approval_id: str, *, now: datetime | None = None) -> ApprovalRequest:
        """批准仍待处理且未过期的请求；参数：审批编号与可选当前时间；返回：更新后的审批请求。"""
        request = self.get(approval_id)
        current = now or datetime.now(UTC)
        if current >= request.expires_at:
            request.status = ApprovalStatus.EXPIRED
            raise ValueError("approval has expired")
        if request.status is not ApprovalStatus.PENDING:
            raise ValueError(f"approval is not pending: {request.status.value}")
        request.status = ApprovalStatus.APPROVED
        return request

    def reject(self, approval_id: str) -> ApprovalRequest:
        """拒绝待处理请求且不产生工具副作用；参数：审批编号；返回：更新后的审批请求。"""
        request = self.get(approval_id)
        if request.status is not ApprovalStatus.PENDING:
            raise ValueError(f"approval is not pending: {request.status.value}")
        request.status = ApprovalStatus.REJECTED
        return request

    def consume(
        self,
        approval_id: str,
        tool_call: ToolCall,
        *,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """以未改变的参数一次性消费已批准请求；参数：审批编号、工具调用及当前时间；返回：已消费请求。"""
        request = self.get(approval_id)
        current = now or datetime.now(UTC)
        if current >= request.expires_at:
            request.status = ApprovalStatus.EXPIRED
            raise ValueError("approval has expired")
        if request.status is not ApprovalStatus.APPROVED:
            raise ValueError(f"approval is not approved: {request.status.value}")
        if tool_call_hash(tool_call) != request.argument_hash:
            raise ValueError("approved tool parameters do not match")
        request.status = ApprovalStatus.CONSUMED
        return request

