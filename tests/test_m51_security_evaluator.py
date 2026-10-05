"""M5.1 deterministic security-suite manifest and evaluator checks."""

from __future__ import annotations

from scripts.run_m51_security import load_cases, run_case


def test_m51_case_manifest_has_unique_expected_cases() -> None:
    cases = load_cases()

    assert [case["id"] for case in cases] == [
        "M51-FLOW-EMAIL-BLOCK",
        "M51-FLOW-MEMORY-BLOCK",
        "M51-FLOW-EMAIL-ALLOW",
        "M51-BENIGN-EMAIL-ALLOW",
    ]


def test_m51_deterministic_security_suite_passes() -> None:
    results = [run_case(case) for case in load_cases()]

    assert all(result["passed"] for result in results)
