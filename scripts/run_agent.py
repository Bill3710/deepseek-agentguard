"""Run the baseline M3 agent against synthetic local tools."""

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
    """Create the command-line parser for offline and DeepSeek runs."""
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
    """Build either the scripted offline provider or configured DeepSeek provider."""
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
    """Print a compact trace without exposing credentials or real external data."""
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
    """Load the synthetic environment, run the agent, and return an exit code."""
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
