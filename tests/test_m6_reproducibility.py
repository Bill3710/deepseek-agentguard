"""M6 reproducibility checks."""

from __future__ import annotations

from agentguard.evaluation import calculate_metrics, content_fingerprint
from scripts.run_m6_evaluation import build_report, evaluate_sources, load_manifest


def test_same_records_produce_same_fingerprint() -> None:
    report_one = build_report(load_manifest())
    report_two = build_report(load_manifest())

    assert report_one["content_fingerprint"] == report_two["content_fingerprint"]


def test_fingerprint_changes_when_record_content_changes() -> None:
    report = build_report(load_manifest())
    records, _ = evaluate_sources(load_manifest())
    original = content_fingerprint(records, calculate_metrics(records))
    records[0].tool_call_count += 1

    assert content_fingerprint(records, calculate_metrics(records)) != original
    assert report["content_fingerprint"] == original
