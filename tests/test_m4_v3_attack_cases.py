"""Structural checks for the staged M4.2/v3 attack corpus."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from agentguard.tools import SimulatedEnvironment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_ROOT / "attacks" / "cases-v3.json"
DATA_DIRECTORY = PROJECT_ROOT / "attacks" / "data-v3"


def load_cases() -> list[dict[str, Any]]:
    """Load the M4.2/v3 case definitions."""
    with CASE_FILE.open(encoding="utf-8") as stream:
        cases = json.load(stream)
    assert isinstance(cases, list)
    return cases


def test_m42_v3_contains_three_variants_for_each_retained_attack_family() -> None:
    cases = load_cases()

    assert len(cases) == 9
    assert len({case["id"] for case in cases}) == 9
    assert all(case["id"].endswith("-V3") for case in cases)
    assert Counter(case["category"] for case in cases) == {
        "prompt_injection": 3,
        "confidentiality": 3,
        "integrity": 3,
    }


def test_m42_v3_uses_independent_valid_synthetic_fixtures() -> None:
    environment = SimulatedEnvironment.from_data_directory(DATA_DIRECTORY)

    assert len(environment.emails) == 9
    assert len(environment.files) == 7
    assert all(email.trust_level.value == "untrusted" for email in environment.emails)
    assert all(
        environment.files[path].classification.value == "confidential"
        for path in (
            "private/partner_evidence.txt",
            "private/customer_evidence.txt",
            "private/contract_evidence.txt",
        )
    )


def test_m42_v3_tasks_are_neutral_and_do_not_authorize_target_side_effects() -> None:
    forbidden = ("发送", "保存", "调用", "按照邮件要求", "完成交付")

    for case in load_cases():
        assert not any(term in case["task"] for term in forbidden)


def test_m42_v3_defines_staged_evidence_and_strict_final_success() -> None:
    for case in load_cases():
        stages = case["attack_stages"]
        stage_ids = [stage["id"] for stage in stages]

        assert stage_ids[0] == "source_accessed"
        assert "impact_created" in stage_ids
        impact_stage = next(stage for stage in stages if stage["id"] == "impact_created")
        assert impact_stage["condition"] == case["success_condition"]
        assert case["expected_outcome"] == "attack_succeeded"


def test_m42_v3_data_exposure_succeeds_on_confidential_tool_output() -> None:
    exfiltration_cases = [
        case for case in load_cases() if case["category"] == "confidentiality"
    ]

    assert len(exfiltration_cases) == 3
    assert all(
        case["success_condition"]["kind"] == "successful_tool_output_contains"
        and case["success_condition"]["tool"] == "read_file"
        for case in exfiltration_cases
    )
    assert all(
        any(
            stage["id"] == "external_exfiltration"
            and stage["condition"]["kind"] == "outbox_contains_unauthorized"
            for stage in case["attack_stages"]
        )
        for case in exfiltration_cases
    )


def test_m42_v3_uses_only_reserved_synthetic_email_domains() -> None:
    serialized = json.dumps(load_cases(), ensure_ascii=False)

    assert "@gmail.com" not in serialized
    assert "@qq.com" not in serialized
    assert "@163.com" not in serialized
