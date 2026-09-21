"""Check DeepSeek API connectivity without printing credentials."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def load_configuration() -> tuple[str, str, str]:
    """Load and validate the minimum configuration required for a live request."""
    load_dotenv(ENV_FILE)

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()

    missing = []
    if not api_key:
        missing.append("DEEPSEEK_API_KEY")
    if not base_url:
        missing.append("DEEPSEEK_BASE_URL")
    if not model:
        missing.append("DEEPSEEK_MODEL")

    if missing:
        names = ", ".join(missing)
        raise ValueError(
            f"Missing configuration: {names}. "
            "Copy .env.example to .env and fill in the local values."
        )

    return api_key, base_url.rstrip("/"), model


def check_connection() -> int:
    """Send one small request and return a process exit code."""
    try:
        api_key, base_url, model = load_configuration()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    print(f"Endpoint: {base_url}")
    print(f"Model: {model}")
    print("API key: configured (value hidden)")

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=30.0,
        max_retries=1,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly DEEPSEEK_CONNECTION_OK.",
                }
            ],
            max_tokens=128,
            extra_body={"thinking": {"type": "disabled"}},
        )
    except AuthenticationError:
        print("Authentication failed. Check DEEPSEEK_API_KEY.", file=sys.stderr)
        return 3
    except RateLimitError:
        print("The request was rate-limited. Wait and try again.", file=sys.stderr)
        return 4
    except APIConnectionError as exc:
        print(f"Connection failed: {type(exc).__name__}", file=sys.stderr)
        return 5
    except APIStatusError as exc:
        print(f"DeepSeek returned HTTP {exc.status_code}.", file=sys.stderr)
        return 6

    choice = response.choices[0]
    print(f"Finish reason: {choice.finish_reason}")

    content = choice.message.content
    if not content:
        reasoning_content = getattr(choice.message, "reasoning_content", None)
        if reasoning_content:
            print(
                "The API returned reasoning content but no final answer.",
                file=sys.stderr,
            )
        else:
            print(
                "The API responded, but the message content was empty.",
                file=sys.stderr,
            )
        return 7

    print(f"Response: {content.strip()}")
    print("DeepSeek connectivity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(check_connection())
