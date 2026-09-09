"""Contract test for documentation operationalization. Does not repair gaps."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_operationalization_unknowns_are_success() -> None:
    from tradingbot.ml.research.documentation_operationalization.run import (
        run_operationalization,
    )

    payload = run_operationalization(write_reports=True)
    assert payload["bootstrap_imports_research"] is False
    assert payload["production_source_for_questions"] is False
    assert payload["gaps"] == [], payload["gaps"]
    classes = payload["question_classes"]
    assert classes["UNKNOWN"] >= 4
    assert classes["CONTRADICTED"] >= 1
    assert classes["DOCUMENTED"] >= 10
    assert payload["watched_vs_impact_map"]["impact_not_watched"] == []
    report = ROOT / "data" / "ml" / "reports" / "documentation_operationalization" / "verification.json"
    assert report.is_file()


def test_bootstrap_py_not_a_runtime_dep() -> None:
    text = (ROOT / "tradingbot" / "application" / "bootstrap.py").read_text(encoding="utf-8")
    assert "documentation_freshness" not in text
    assert "documentation_consistency" not in text
    assert "ml.research" not in text
