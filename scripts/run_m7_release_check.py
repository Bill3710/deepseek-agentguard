"""Run public-release checks without reading ignored local secret files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "m7-release-check-results.json"
REQUIRED_PUBLIC_FILES = (
    "README.md",
    "SECURITY.md",
    "docs/architecture.md",
    "docs/public-demo.md",
    "docs/quality-assurance.md",
    "docs/threat-model.md",
    "results/m6-evaluation-results.json",
    "results/m6-evaluation-summary.md",
)
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "bearer_token": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b"),
    "model_api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "configured_api_key": re.compile(
        r"(?i)\b(?:DEEPSEEK|OPENAI)_API_KEY\s*=\s*[^\s#]+"
    ),
}
PLACEHOLDER_MARKERS = (
    "replace_with",
    "your_key",
    "example",
    "placeholder",
    "test_",
    "测试",
    "你的",
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def repository_files() -> list[Path]:
    """List tracked and untracked non-ignored files without opening `.env`."""
    result = _git("ls-files", "-co", "--exclude-standard", "-z")
    if result.returncode != 0:
        raise RuntimeError("unable to list repository files")
    return [
        PROJECT_ROOT / name
        for name in result.stdout.split("\0")
        if name and (PROJECT_ROOT / name).is_file()
    ]


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def scan_secrets(paths: list[Path]) -> list[dict[str, Any]]:
    """Return locations and rule names only; never return matched values."""
    findings: list[dict[str, Any]] = []
    for path in paths:
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            normalized = line.casefold()
            for rule, pattern in SECRET_PATTERNS.items():
                if not pattern.search(line):
                    continue
                if any(marker.casefold() in normalized for marker in PLACEHOLDER_MARKERS):
                    continue
                findings.append(
                    {
                        "path": _display_path(path),
                        "line": line_number,
                        "rule": rule,
                    }
                )
    return findings


def check_markdown_links(paths: list[Path]) -> list[dict[str, Any]]:
    """Check repository-relative Markdown links and return broken targets."""
    broken: list[dict[str, Any]] = []
    for path in paths:
        if path.suffix.casefold() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            raw_target = match.group(1).strip().strip("<>")
            if not raw_target or raw_target.startswith("#"):
                continue
            if re.match(
                r"^(?:https?|mailto|codex|app):",
                raw_target,
                re.IGNORECASE,
            ):
                continue
            target_text = unquote(raw_target.split("#", 1)[0])
            target = (path.parent / target_text).resolve()
            if target.exists():
                continue
            line_number = text.count("\n", 0, match.start()) + 1
            broken.append(
                {
                    "path": _display_path(path),
                    "line": line_number,
                    "target": raw_target,
                }
            )
    return broken


def _check(name: str, passed: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": passed, "details": details}


def run_checks() -> list[dict[str, Any]]:
    """Run deterministic repository checks and one offline public demo."""
    paths = repository_files()
    status = _git("status", "--porcelain")
    tracked_env = _git("ls-files", ".env")
    remote = _git("remote", "get-url", "origin")
    findings = scan_secrets(paths)
    broken_links = check_markdown_links(paths)
    missing = [name for name in REQUIRED_PUBLIC_FILES if not (PROJECT_ROOT / name).is_file()]
    demo = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "run_agent.py"),
            "--provider",
            "fake",
            "搜索包含 invoice 的邮件",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return [
        _check(
            "repository_clean",
            status.returncode == 0 and not status.stdout.strip(),
            {"changed_entry_count": len(status.stdout.splitlines())},
        ),
        _check(
            "env_not_tracked",
            tracked_env.returncode == 0 and not tracked_env.stdout.strip(),
            {},
        ),
        _check(
            "origin_configured",
            remote.returncode == 0 and remote.stdout.strip().startswith("https://github.com/"),
            {"configured": remote.returncode == 0 and bool(remote.stdout.strip())},
        ),
        _check("secret_scan", not findings, {"findings": findings}),
        _check("markdown_links", not broken_links, {"broken": broken_links}),
        _check("required_public_files", not missing, {"missing": missing}),
        _check(
            "offline_public_demo",
            demo.returncode == 0,
            {"return_code": demo.returncode},
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checks = run_checks()
    passed = sum(check["passed"] for check in checks)
    report = {
        "suite": "M7 发布准备检查",
        "generated_at": datetime.now(UTC).isoformat(),
        "network_used": False,
        "passed": passed,
        "total": len(checks),
        "release_ready": passed == len(checks),
        "checks": checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"M7 release checks: {passed}/{len(checks)} passed")
    for check in checks:
        state = "PASS" if check["passed"] else "FAIL"
        print(f"[{state}] {check['name']}")
    print(f"Report: {args.output.name}")
    return 0 if report["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
