"""使用合成本地工具运行 M3 基线智能体。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentguard.providers import (
    DeepSeekProvider,
    FakeProvider,
    ModelProvider,
    ProviderConfigurationError,
)
from agentguard.runner import AgentRunner
from agentguard.schemas import AgentRunResult, AgentRunStatus, ProviderResponse, ToolCall
from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"
ENV_FILE = PROJECT_ROOT / ".env"


def build_parser() -> argparse.ArgumentParser:
    """创建离线与 DeepSeek 运行的命令行解析器；参数：无；返回：解析器。"""
    parser = argparse.ArgumentParser(
        description="Run the baseline AgentGuard agent with synthetic local tools.",
    )
    parser.add_argument("task", help="Task for the baseline agent")
    parser.add_argument(
        "--provider",
        choices=("fake", "deepseek"),
        default="fake",
        help="Model provider. The fake provider is offline and deterministic.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="Maximum number of model turns before stopping (default: 8).",
    )
    return parser


def build_provider(name: str) -> ModelProvider:
    """创建离线或 DeepSeek 提供方；参数：name 提供方名称；返回：模型提供方。"""
    if name == "deepseek":
        return DeepSeekProvider.from_env(ENV_FILE)

    return FakeProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall(
                        id="offline-call-1",
                        name="search_emails",
                        arguments={"query": "invoice"},
                    )
                ],
                finish_reason="tool_calls",
                model="fake-provider",
            ),
            ProviderResponse(
                content=(
                    "Offline demonstration completed after searching the synthetic "
                    "mailbox for 'invoice'."
                ),
                finish_reason="stop",
                model="fake-provider",
            ),
        ]
    )


def print_result(result: AgentRunResult) -> None:
    """输出不含凭据和真实外部数据的简要轨迹；参数：result 运行结果；返回：无。"""
    print(f"Status: {result.status.value}")
    for step in result.steps:
        print(f"Step {step.step_number}: model={step.model_response.model or 'unknown'}")
        for tool_call, tool_result in zip(
            step.model_response.tool_calls,
            step.tool_results,
            strict=True,
        ):
            outcome = "success" if tool_result.success else "failed"
            print(f"  Tool: {tool_call.name} ({outcome})")
            if tool_result.error:
                print(f"  Error: {tool_result.error}")
    if result.final_answer:
        print(f"Final answer: {result.final_answer}")
    if result.error:
        print(f"Run error: {result.error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """加载模拟环境并运行智能体；参数：argv 可选命令行参数；返回：进程退出码。"""
    args = build_parser().parse_args(argv)
    try:
        provider = build_provider(args.provider)
        environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)
        runner = AgentRunner(
            provider=provider,
            environment=environment,
            max_steps=args.max_steps,
        )
        result = runner.run(args.task)
    except (ProviderConfigurationError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    print(f"Provider: {args.provider}")
    print("Environment: synthetic local data; all tools are simulated")
    print_result(result)
    return 0 if result.status is AgentRunStatus.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(main())
