"""Prevent feature creep in future M4.2/v3 optimization versions."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from agentguard.tools import TOOL_REGISTRY
from scripts.run_m4_attacks import ATTACK_STATUSES

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ATTACK_DIRECTORY = PROJECT_ROOT / "attacks"
FREEZE_FILE = ATTACK_DIRECTORY / "v3-feature-freeze.json"


def load_json(path: Path) -> Any:
    """Load one UTF-8 JSON document."""
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def condition_kinds(case: dict[str, Any]) -> set[str]:
    """Return every final and staged condition kind used by one case."""
    return {case["success_condition"]["kind"]} | {
        stage["condition"]["kind"] for stage in case["attack_stages"]
    }


def test_v3_optimization_versions_obey_the_feature_freeze() -> None:
    freeze = load_json(FREEZE_FILE)
    case_files = sorted(ATTACK_DIRECTORY.glob(freeze["case_file_pattern"]))

    assert freeze["status"] == "frozen"
    assert case_files
    for case_file in case_files:
        cases = load_json(case_file)
        assert {case["id"] for case in cases} == set(freeze["case_ids"])
        assert Counter(case["category"] for case in cases) == Counter(
            freeze["category_counts"]
        )
        for case in cases:
            assert set(case) == set(freeze["allowed_case_fields"])
            assert case["vector"] in freeze["allowed_vectors"]
            assert case["expected_outcome"] == "attack_succeeded"
            assert case["success_condition"]["kind"] == freeze[
                "success_kind_by_category"
            ][case["category"]]
            assert {stage["id"] for stage in case["attack_stages"]} <= set(
                freeze["allowed_stage_ids"]
            )
            assert "impact_created" in {
                stage["id"] for stage in case["attack_stages"]
            }
            assert condition_kinds(case) <= set(freeze["allowed_condition_kinds"])


def test_v3_feature_freeze_locks_tools_statuses_and_data_file_types() -> None:
    freeze = load_json(FREEZE_FILE)
    data_directories = sorted(
        path
        for path in ATTACK_DIRECTORY.glob(freeze["data_directory_pattern"])
        if path.is_dir()
    )

    assert set(TOOL_REGISTRY) == set(freeze["allowed_tools"])
    assert set(ATTACK_STATUSES) == set(freeze["attack_statuses"])
    assert data_directories
    for data_directory in data_directories:
        assert {path.name for path in data_directory.iterdir() if path.is_file()} == set(
            freeze["allowed_data_files"]
        )
