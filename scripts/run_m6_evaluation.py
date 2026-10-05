"""Aggregate existing M4/M5/M5.1 reports into reproducible M6 metrics."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentguard.evaluation import (
    calculate_metrics,
    content_fingerprint,
    normalize_report,
    render_markdown,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "tests" / "cases" / "m6_evaluation_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "m6-evaluation-results.json"
DEFAULT_SUMMARY = PROJECT_ROOT / "results" / "m6-evaluation-summary.md"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args(argv)


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[dict[str, Any]]:
    """Load a unique, non-empty source-report manifest."""
    with path.open(encoding="utf-8") as stream:
        sources = json.load(stream)
    if not isinstance(sources, list) or not sources:
        raise ValueError("M6 evaluation manifest must be a non-empty list")
    identifiers = [source["id"] for source in sources]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("M6 source IDs must be unique")
    return sources


def evaluate_sources(
    sources: list[dict[str, Any]],
    *,
    project_root: Path = PROJECT_ROOT,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Normalize every report and calculate per-source comparisons."""
    all_records = []
    comparisons = []
    for source in sources:
        report_path = project_root / source["path"]
        with report_path.open(encoding="utf-8") as stream:
            report = json.load(stream)
        records = normalize_report(
            report,
            adapter=source["adapter"],
            source_id=source["id"],
            defense_version=source["defense_version"],
        )
        if not records:
            raise ValueError(f"M6 source produced no records: {source['id']}")
        all_records.extend(records)
        comparisons.append(
            {
                "source_id": source["id"],
                "label": source["label"],
                "defense_version": source["defense_version"],
                "comparison_scope": source["comparison_scope"],
                "interpretation": source["interpretation"],
                "metrics": calculate_metrics(records),
            }
        )
    return all_records, comparisons


def build_report(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a public-safe M6 report with a stable content fingerprint."""
    records, comparisons = evaluate_sources(sources)
    metrics = calculate_metrics(records)
    return {
        "suite": "M6 自动化攻防评测",
        "generated_at": datetime.now(UTC).isoformat(),
        "network_used": False,
        "contains_real_data": False,
        "source_count": len(sources),
        "record_count": len(records),
        "content_fingerprint": content_fingerprint(records, metrics),
        "metric_rules": {
            "not_triggered_is_policy_block": False,
            "errors_in_rate_denominators": False,
            "rates_use_evaluable_records_only": True,
        },
        "sources": comparisons,
        "metrics": metrics,
        "records": [record.model_dump(mode="json") for record in records],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sources = load_manifest(args.manifest)
    report = build_report(sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        render_markdown(report["metrics"], report["sources"]),
        encoding="utf-8",
    )
    print(f"M6 normalized records: {report['record_count']}")
    print(f"Fingerprint: {report['content_fingerprint']}")
    print(f"JSON report: {args.output.name}")
    print(f"Markdown summary: {args.summary.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
