"""Phase 1.5.71 — documentation memory baseline (offline)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_baseline_writes_json_and_kinds() -> None:
    from tradingbot.ml.research.documentation_memory_hardening.baseline import run_baseline

    payload = run_baseline(write_reports=True)
    assert payload["questions"]["A_entry_sufficient_as_navigation"]["kind"] == "DERIVED FACT"
    assert payload["questions"]["B_fresh_model_without_repo"]["kind"] == "DERIVED FACT"
    assert "UNKNOWN" in payload["claim_kinds_used"]
    assert "ASSUMPTION" in payload["claim_kinds_used"]
    assert payload["core_missing"] == []
    assert any(p.endswith("PROJECT_SOURCE_OF_TRUTH.md") for p in payload["canonical_entry_true_files"])
    path = ROOT / "data" / "ml" / "reports" / "documentation_memory_hardening" / "baseline.json"
    assert path.is_file()
    text = (ROOT / "docs_v2" / "01_truth" / "DOCUMENTATION_MEMORY_BASELINE.md").read_text(encoding="utf-8")
    assert "DERIVED FACT" in text
    assert "Do not collapse" in text or "not collapsed" in text.lower() or "does not" in text.lower()
