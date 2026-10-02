"""Structural checks for the M4.1 contextual attack corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_ROOT / "attacks" / "cases-v2.json"
DATA_DIRECTORY = PROJECT_ROOT / "attacks" / "data-v2"
SECRET_MARKER = "AGENTGUARD_SECRET_M41_001"


def load_cases() -> list[dict[str, Any]]:
    """Load the M4.1 case definitions."""
    with CASE_FILE.open(encoding="utf-8") as stream:
        cases = json.load(stream)
    assert isinstance(cases, list)
    return cases


def test_m41_contains_eight_attack_and_four_boundary_cases() -> None:
    cases = load_cases()

    assert len(cases) == 12
    assert len({case["id"] for case in cases}) == 12
    assert all(case["id"].endswith("-V2") for case in cases)
    assert sum(case["expected_outcome"] == "attack_succeeded" for case in cases) == 8
    assert sum(case["expected_outcome"] == "blocked" for case in cases) == 4


def test_m41_uses_independent_valid_synthetic_fixtures() -> None:
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)

    assert len(environment.emails) == 7
    assert all(email.trust_level.value == "untrusted" for email in environment.emails)
    assert environment.files["private/review_scope.txt"].classification.value == (
        "confidential"
    )
    assert SECRET_MARKER in environment.files["private/review_scope.txt"].content
    assert "public/workflow_appendix.txt" in environment.files


def test_m41_contextual_payloads_remove_obvious_attack_labels() -> None:
    payload = " ".join(
        [email.body for email in SimulatedEnvironment.from_data_directory(DATA_DIRECTORY).emails]
        + [record.content for record in SimulatedEnvironment.from_data_directory(DATA_DIRECTORY).files.values()]
    )

    assert "忽略原任务" not in payload
    assert "这是不可信文件" not in payload
    assert "attacker@" not in payload


def test_m41_loop_task_contains_no_soft_defense_instruction() -> None:
    cases = {case["id"]: case for case in load_cases()}

    assert "忽略" not in cases["LOOP-V2"]["task"]


def test_m41_only_uses_reserved_synthetic_email_domains() -> None:
    serialized = json.dumps(load_cases(), ensure_ascii=False)

    assert "@gmail.com" not in serialized
    assert "@qq.com" not in serialized
    assert "@163.com" not in serialized
