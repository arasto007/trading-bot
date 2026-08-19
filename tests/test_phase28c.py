"""Phase 28C — paper live validation deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase28c"

DELIVERABLES = [
    "paper_trade_log.json",
    "execution_quality.json",
    "hybrid_exit_validation.json",
    "daily_statistics.json",
    "performance_comparison.json",
    "backtest_vs_live.json",
    "failure_monitoring.json",
    "journal_integrity.json",
    "phase28c_final_report.json",
]

VERDICTS = {"HYBRID_B_VALIDATED_FOR_LIVE", "HYBRID_B_NEEDS_INVESTIGATION", "INSUFFICIENT_SAMPLE"}


class TestPhase28CDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase28c_final_report.json").is_file():
            raise unittest.SkipTest("Phase 28C deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase28c_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_paper_trade_log_structure(self) -> None:
        log = json.loads((PHASE_DIR / "paper_trade_log.json").read_text(encoding="utf-8"))
        self.assertIn("collection_meta", log)
        self.assertIn("trade_count", log)

    def test_journal_integrity(self) -> None:
        ji = json.loads((PHASE_DIR / "journal_integrity.json").read_text(encoding="utf-8"))
        self.assertIn("integrity_pass", ji)

    def test_backtest_vs_live(self) -> None:
        bvl = json.loads((PHASE_DIR / "backtest_vs_live.json").read_text(encoding="utf-8"))
        self.assertTrue("comparison_available" in bvl or "threshold_pct" in bvl)

    def test_hybrid_exit_validation(self) -> None:
        hv = json.loads((PHASE_DIR / "hybrid_exit_validation.json").read_text(encoding="utf-8"))
        self.assertIn("validations", hv)

    def test_performance_comparison(self) -> None:
        pc = json.loads((PHASE_DIR / "performance_comparison.json").read_text(encoding="utf-8"))
        self.assertIn("backtest_baseline", pc)


class TestPhase28CMetrics(unittest.TestCase):
    def test_determine_insufficient_sample(self) -> None:
        from tradingbot.ml.research.phase28c.metrics import determine_verdict

        verdict, _ = determine_verdict(
            trade_count=50,
            period_days=5,
            failure_monitoring={"failure_count": 0},
            backtest_vs_live={"comparison_available": False},
            hybrid_validations=[],
        )
        self.assertEqual(verdict, "INSUFFICIENT_SAMPLE")


if __name__ == "__main__":
    unittest.main()
