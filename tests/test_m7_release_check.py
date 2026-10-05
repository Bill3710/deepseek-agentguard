"""M7 release-check helper tests."""

from __future__ import annotations

from pathlib import Path

from scripts.run_m7_release_check import check_markdown_links, scan_secrets


def test_secret_scan_reports_rule_and_location_without_value(tmp_path: Path) -> None:
    secret = "sk-" + "abcdefghijklmnopqrstuvwx"
    target = tmp_path / "unsafe.txt"
    target.write_text(f"credential={secret}\n", encoding="utf-8")

    findings = scan_secrets([target])

    assert findings[0]["rule"] == "model_api_key"
    assert findings[0]["line"] == 1
    assert secret not in str(findings)


def test_secret_scan_allows_documented_placeholder(tmp_path: Path) -> None:
    target = tmp_path / "template.env"
    target.write_text("DEEPSEEK_API_KEY=replace_with_your_key\n", encoding="utf-8")

    assert scan_secrets([target]) == []


def test_markdown_link_check_accepts_existing_relative_target(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("# Target\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text("[target](target.md)\n", encoding="utf-8")

    assert check_markdown_links([source, target]) == []


def test_markdown_link_check_reports_missing_target(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("[missing](missing.md)\n", encoding="utf-8")

    broken = check_markdown_links([source])

    assert broken[0]["line"] == 1
    assert broken[0]["target"] == "missing.md"
