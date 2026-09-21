"""Deterministic local tools with no real external side effects."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import ValidationError

from agentguard.schemas import (
    EmailRecord,
    FileRecord,
    MemoryEntry,
    ReadFileArgs,
    SaveMemoryArgs,
    SearchEmailsArgs,
    SendEmailArgs,
    SimulatedEmail,
    StrictModel,
    ToolResult,
)

MAX_SEARCH_RESULTS = 20
ALLOWED_TEST_DOMAINS = frozenset({"example.com", "example.net", "example.test"})


@dataclass(slots=True)
class SimulatedEnvironment:
    """Isolated state used by one local AgentGuard run."""

    emails: list[EmailRecord]
    files: dict[str, FileRecord]
    outbox: list[SimulatedEmail] = field(default_factory=list)
    memory: list[MemoryEntry] = field(default_factory=list)

    @classmethod
    def from_data_directory(cls, data_directory: Path) -> SimulatedEnvironment:
        """Load and validate synthetic email and file fixtures."""
        email_path = data_directory / "emails.json"
        file_path = data_directory / "files.json"

        with email_path.open(encoding="utf-8-sig") as stream:
            raw_emails = json.load(stream)
        with file_path.open(encoding="utf-8-sig") as stream:
            raw_files = json.load(stream)

        if not isinstance(raw_emails, list):
            raise TypeError("emails.json must contain a JSON array")
        if not isinstance(raw_files, dict):
            raise TypeError("files.json must contain a JSON object")

        emails = [EmailRecord.model_validate(item) for item in raw_emails]
        files = {
            _normalize_simulated_path(path): FileRecord.model_validate(record)
            for path, record in raw_files.items()
        }
        return cls(emails=emails, files=files)


def _failed(tool_name: str, error: str) -> ToolResult:
    return ToolResult(success=False, tool_name=tool_name, error=error)


def _normalize_simulated_path(raw_path: str) -> str:
    """Normalize a synthetic path and reject absolute or traversing paths."""
    windows_path = PureWindowsPath(raw_path)
    normalized_text = raw_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized_text)

    if windows_path.is_absolute() or posix_path.is_absolute():
        raise ValueError("absolute paths are not allowed")
    if any(part in {"..", "."} for part in posix_path.parts):
        raise ValueError("relative path traversal is not allowed")
    if not posix_path.parts:
        raise ValueError("path cannot be empty")

    return posix_path.as_posix()


def _is_reserved_test_recipient(recipient: str) -> bool:
    """Return whether a recipient uses an RFC-reserved example domain."""
    if recipient.count("@") != 1:
        return False
    local_part, domain = recipient.rsplit("@", 1)
    return bool(local_part) and domain.casefold() in ALLOWED_TEST_DOMAINS


def search_emails(
    env: SimulatedEnvironment,
    args: SearchEmailsArgs,
) -> ToolResult:
    """Search synthetic email subjects and bodies without changing state."""
    query = args.query.casefold()
    all_matches = [
        email
        for email in env.emails
        if query in email.subject.casefold() or query in email.body.casefold()
    ]
    selected = all_matches[:MAX_SEARCH_RESULTS]
    return ToolResult(
        success=True,
        tool_name="search_emails",
        output=[email.model_dump(mode="json", by_alias=True) for email in selected],
        metadata={
            "match_count": len(all_matches),
            "returned_count": len(selected),
            "truncated": len(all_matches) > len(selected),
        },
    )


def read_file(
    env: SimulatedEnvironment,
    args: ReadFileArgs,
) -> ToolResult:
    """Read a file only from the in-memory synthetic file collection."""
    try:
        normalized_path = _normalize_simulated_path(args.path)
    except ValueError as exc:
        return _failed("read_file", str(exc))

    record = env.files.get(normalized_path)
    if record is None:
        return _failed("read_file", f"simulated file not found: {normalized_path}")

    return ToolResult(
        success=True,
        tool_name="read_file",
        output={
            "path": normalized_path,
            **record.model_dump(mode="json"),
        },
    )


def send_email(
    env: SimulatedEnvironment,
    args: SendEmailArgs,
) -> ToolResult:
    """Append an email to the local outbox without sending network traffic."""
    if not _is_reserved_test_recipient(args.to):
        return _failed(
            "send_email",
            "recipient must use example.com, example.net, or example.test",
        )

    email = SimulatedEmail(
        id=f"outbox-{len(env.outbox) + 1:03d}",
        to=args.to,
        subject=args.subject,
        body=args.body,
    )
    env.outbox.append(email)
    return ToolResult(
        success=True,
        tool_name="send_email",
        output=email.model_dump(mode="json"),
        metadata={"simulated": True},
    )


def save_memory(
    env: SimulatedEnvironment,
    args: SaveMemoryArgs,
) -> ToolResult:
    """Append one entry to the local in-memory store."""
    entry = MemoryEntry(
        id=f"memory-{len(env.memory) + 1:03d}",
        content=args.content,
        source=args.source,
    )
    env.memory.append(entry)
    return ToolResult(
        success=True,
        tool_name="save_memory",
        output=entry.model_dump(mode="json"),
        metadata={"simulated": True},
    )


ToolHandler = Callable[[SimulatedEnvironment, Any], ToolResult]

TOOL_ARGUMENT_MODELS: dict[str, type[StrictModel]] = {
    "search_emails": SearchEmailsArgs,
    "read_file": ReadFileArgs,
    "send_email": SendEmailArgs,
    "save_memory": SaveMemoryArgs,
}

TOOL_REGISTRY: dict[str, ToolHandler] = {
    "search_emails": search_emails,
    "read_file": read_file,
    "send_email": send_email,
    "save_memory": save_memory,
}


def execute_tool(
    env: SimulatedEnvironment,
    tool_name: str,
    arguments: dict[str, Any],
) -> ToolResult:
    """Validate and execute one allowlisted simulated tool."""
    argument_model = TOOL_ARGUMENT_MODELS.get(tool_name)
    handler = TOOL_REGISTRY.get(tool_name)
    if argument_model is None or handler is None:
        return _failed(tool_name or "unknown", f"unknown tool: {tool_name}")

    try:
        validated_arguments = argument_model.model_validate(arguments)
    except ValidationError as exc:
        return _failed(
            tool_name,
            f"invalid tool arguments: {exc.error_count()} validation error(s)",
        )

    return handler(env, validated_arguments)
