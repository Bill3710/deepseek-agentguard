"""Structural checks for the five M3 online usability cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentguard.tools import TOOL_REGISTRY

CASE_FILE = Path(__file__).parent / "cases" / "m3_usability_cases.json"
REQUIRED_FIELDS = {
    "id",
    "name",
    "task",
    "expected_status",
    "expected_tools",
    "expected_facts",
    "expected_state",
    "pass_criteria",
}


def load_cases() -> list[dict[str, Any]]:
    """Load the public M3 usability case definitions."""
    with CASE_FILE.open(encoding="utf-8") as stream:
        cases = json.load(stream)
    assert isinstance(cases, list)
    return cases


def test_m3_suite_contains_five_well_formed_unique_cases() -> None:
    cases = load_cases()

    assert len(cases) == 5
    assert len({case["id"] for case in cases}) == 5
    for case in cases:
        assert set(case) == REQUIRED_FIELDS
        assert case["id"].startswith("m3-")
        assert case["name"]
        assert case["task"]
        assert case["expected_status"] == "completed"
        assert isinstance(case["expected_tools"], list)
        assert set(case["expected_tools"]) <= set(TOOL_REGISTRY)
        assert isinstance(case["expected_facts"], dict)
        assert isinstance(case["expected_state"], dict)
        assert case["pass_criteria"]


def test_m3_suite_covers_no_tool_and_every_allowlisted_tool() -> None:
    cases = load_cases()
    covered_tools = {
        tool_name
        for case in cases
        for tool_name in case["expected_tools"]
    }

    assert any(not case["expected_tools"] for case in cases)
    assert covered_tools == set(TOOL_REGISTRY)


def test_email_case_uses_only_reserved_test_recipient() -> None:
    cases = load_cases()
    email_case = next(case for case in cases if "send_email" in case["expected_tools"])

    assert email_case["expected_state"]["recipient"].endswith("@example.test")
