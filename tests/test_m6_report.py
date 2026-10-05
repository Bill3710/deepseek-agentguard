"""M6 manifest, real-report adapters, and Markdown report tests."""

from __future__ import annotations

from agentguard.evaluation import render_markdown
from scripts.run_m6_evaluation import build_report, load_manifest


def test_default_manifest_covers_baseline_m5_and_m51() -> None:
    sources = load_manifest()

    assert [source["defense_version"] for source in sources] == [
        "M4-none",
        "M5",
        "M5",
        "M5.1",
    ]


def test_default_reports_normalize_without_sensitive_payloads() -> None:
    report = build_report(load_manifest())

    assert report["record_count"] == 109
    assert report["network_used"] is False
    assert report["metrics"]["attack"]["total"] == 60
    assert report["metrics"]["benign"]["total"] == 45
    assert report["metrics"]["control"] == {"total": 4, "passed": 4}
    assert all("task" not in record for record in report["records"])
    assert all("final_answer" not in record for record in report["records"])


def test_markdown_explains_not_triggered_denominator_rule() -> None:
    report = build_report(load_manifest())
    markdown = render_markdown(report["metrics"], report["sources"])

    assert "M6 自动化攻防评测摘要" in markdown
    assert "`NOT_TRIGGERED` 不计为策略阻止" in markdown
    assert "m4-v3.3-injection-baseline" in markdown
    assert "攻击成功不等同于参数级直接服从" in markdown
