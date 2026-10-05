"""定义模型提供方抽象，以及确定性的伪提供方和 DeepSeek 实现。"""

from __future__ import annotations

import json
import os
from collections import deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from agentguard.schemas import ChatMessage, MessageRole, ProviderResponse, ToolCall

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


class ProviderError(RuntimeError):
    """模型提供方通用异常基类；参数：继承 RuntimeError 的错误消息。"""


class ProviderConfigurationError(ProviderError):
    """提供方配置缺失或无效时抛出的异常；参数：错误消息。"""


class ProviderResponseError(ProviderError):
    """提供方返回格式错误或空响应时抛出的异常；参数：错误消息。"""


class ProviderAuthenticationError(ProviderError):
    """DeepSeek 拒绝 API 凭据时抛出的异常；参数：错误消息。"""


class ProviderConnectionError(ProviderError):
    """无法连接 DeepSeek 服务时抛出的异常；参数：错误消息。"""


class ProviderRateLimitError(ProviderError):
    """DeepSeek 对请求限流时抛出的异常；参数：错误消息。"""


class ProviderAPIError(ProviderError):
    """DeepSeek API 返回其他错误时抛出的异常；参数：错误消息。"""


@runtime_checkable
class ModelProvider(Protocol):
    """智能体执行器使用的模型提供方协议；实现类需提供 complete 方法。"""

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ProviderResponse:
        """生成一次标准化模型响应；参数：messages 对话消息、tools 可选工具定义；返回：提供方响应。"""
        ...


class FakeProvider:
    """无需网络或费用地返回预置响应；参数：responses 按顺序消费的响应序列。"""

    def __init__(self, responses: Sequence[ProviderResponse]) -> None:
        """复制并保存预置响应；参数：responses 响应序列；返回：无。"""
        self._responses = deque(response.model_copy(deep=True) for response in responses)
        self.calls: list[dict[str, Any]] = []

    @property
    def remaining_responses(self) -> int:
        """统计尚未消费的预置响应；参数：无；返回：剩余数量。"""
        return len(self._responses)

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ProviderResponse:
        """记录请求并返回下一条预置响应；参数：消息与可选工具；返回：提供方响应。"""
        self.calls.append(
            {
                "messages": [message.model_copy(deep=True) for message in messages],
                "tools": deepcopy(list(tools)) if tools is not None else None,
            }
        )
        if not self._responses:
            raise ProviderResponseError("FakeProvider has no responses remaining")
        return self._responses.popleft().model_copy(deep=True)


class DeepSeekProvider:
    """通过 OpenAI 兼容 SDK 调用 DeepSeek；参数：密钥、地址、模型、超时、重试、令牌上限和可选客户端。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 30.0,
        max_retries: int = 1,
        max_tokens: int = 1024,
        client: Any | None = None,
    ) -> None:
        """验证配置并初始化客户端；参数：连接与生成配置；返回：无；异常：无效配置时抛出配置错误。"""
        api_key = api_key.strip()
        base_url = base_url.strip().rstrip("/")
        model = model.strip()
        if not api_key:
            raise ProviderConfigurationError("DEEPSEEK_API_KEY is required")
        if not base_url:
            raise ProviderConfigurationError("DEEPSEEK_BASE_URL is required")
        if not model:
            raise ProviderConfigurationError("DEEPSEEK_MODEL is required")
        if timeout <= 0:
            raise ProviderConfigurationError("timeout must be greater than zero")
        if max_retries < 0:
            raise ProviderConfigurationError("max_retries cannot be negative")
        if max_tokens <= 0:
            raise ProviderConfigurationError("max_tokens must be greater than zero")

        self.base_url = base_url
        self.model = model
        self.max_tokens = max_tokens
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        **overrides: Any,
    ) -> DeepSeekProvider:
        """从环境创建提供方且不暴露密钥；参数：env_file 配置文件及覆盖项；返回：DeepSeek 提供方。"""
        load_dotenv(dotenv_path=env_file, override=False)
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **overrides,
        )

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ProviderResponse:
        """调用一次 DeepSeek 并标准化文本和工具调用；参数：消息与可选工具；返回：提供方响应。"""
        if not messages:
            raise ProviderConfigurationError("at least one chat message is required")

        request: dict[str, Any] = {
            "model": self.model,
            "messages": [_serialize_message(message) for message in messages],
            "max_tokens": self.max_tokens,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if tools is not None:
            request["tools"] = deepcopy(list(tools))

        try:
            response = self._client.chat.completions.create(**request)
        except AuthenticationError as exc:
            raise ProviderAuthenticationError(
                "DeepSeek authentication failed; check DEEPSEEK_API_KEY"
            ) from exc
        except RateLimitError as exc:
            raise ProviderRateLimitError("DeepSeek rate limit exceeded") from exc
        except APIConnectionError as exc:
            raise ProviderConnectionError("could not connect to DeepSeek") from exc
        except APIStatusError as exc:
            raise ProviderAPIError(
                f"DeepSeek returned HTTP {exc.status_code}"
            ) from exc
        except OpenAIError as exc:
            raise ProviderAPIError("DeepSeek request failed") from exc

        return _parse_response(response, fallback_model=self.model)


def _serialize_message(message: ChatMessage) -> dict[str, Any]:
    """将标准消息转为 OpenAI 兼容请求数据；参数：message 聊天消息；返回：序列化字典。"""
    serialized: dict[str, Any] = {"role": message.role.value}
    if message.content is not None:
        serialized["content"] = message.content
    elif message.role is MessageRole.ASSISTANT:
        serialized["content"] = None

    if message.tool_call_id is not None:
        serialized["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        serialized["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(
                        tool_call.arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }
            for tool_call in message.tool_calls
        ]
    return serialized


def _parse_response(response: Any, *, fallback_model: str) -> ProviderResponse:
    """标准化 SDK 响应并拒绝错误工具参数；参数：原始响应和备用模型名；返回：提供方响应。"""
    choices = getattr(response, "choices", None)
    if not choices:
        raise ProviderResponseError("DeepSeek returned no choices")

    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None:
        raise ProviderResponseError("DeepSeek returned a choice without a message")

    content = getattr(message, "content", None)
    if isinstance(content, str):
        content = content.strip() or None

    normalized_calls = []
    for raw_call in getattr(message, "tool_calls", None) or []:
        function = getattr(raw_call, "function", None)
        call_id = getattr(raw_call, "id", None)
        name = getattr(function, "name", None) if function is not None else None
        raw_arguments = (
            getattr(function, "arguments", None) if function is not None else None
        )
        if not call_id or not name or not isinstance(raw_arguments, str):
            raise ProviderResponseError("DeepSeek returned a malformed tool call")
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                f"DeepSeek returned invalid JSON arguments for tool {name}"
            ) from exc
        if not isinstance(arguments, dict):
            raise ProviderResponseError(
                f"DeepSeek tool arguments for {name} must be a JSON object"
            )
        normalized_calls.append(
            ToolCall(id=call_id, name=name, arguments=arguments)
        )

    try:
        return ProviderResponse(
            content=content,
            tool_calls=normalized_calls,
            finish_reason=getattr(choice, "finish_reason", None),
            model=getattr(response, "model", None) or fallback_model,
        )
    except ValueError as exc:
        raise ProviderResponseError("DeepSeek returned an empty response") from exc
