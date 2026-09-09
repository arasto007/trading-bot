"""Documentation verification entry tests. Offline. No snapshot rewrite."""

from __future__ import annotations

from pathlib import Path

from tradingbot.ml.research.documentation_freshness.scanner import SNAPSHOT
from tradingbot.ml.research.documentation_verification.run import run_verification

ROOT = Path(__file__).resolve().parents[1]


def test_documentation_verification_gate() -> None:
    before = SNAPSHOT.read_bytes()
    payload = run_verification(write_reports=True)
    after = SNAPSHOT.read_bytes()
    assert before == after
    assert payload["canonical_entry_count"] == 1
    assert payload["bootstrap_imports_research"] is False
    assert payload["watch_reasons_complete"] is True
    assert payload["question_failures"] == [], payload["question_failures"]
    assert payload["hallucination_failures"] == [], payload["hallucination_failures"]
    assert payload["failed_gates"] == [], payload["failed_gates"]
    assert payload["verdict"] == "100% COMPLETE FOR DECISION-MAKING"
    assert (ROOT / "data/ml/reports/documentation_verification/verification.json").is_file()
    report = (ROOT / "docs_v2/01_truth/DOCUMENTATION_VERIFICATION_REPORT.md").read_text(encoding="utf-8")
    assert "# DOCUMENTATION 100% VERIFICATION REPORT" in report
    assert "Operator-effective state: UNKNOWN" in report
