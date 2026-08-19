"""Phase 28D — backtest deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase28d"

DELIVERABLES = [
    "backtest_summary.json",
    "trade_log.json",
    "daily_statistics.json",
    "weekly_statistics.json",
    "monthly_statistics.json",
    "direction_analysis.json",
    "session_analysis.json",
    "regime_analysis.json",
    "engine_analysis.json",
    "risk_analysis.json",
    "execution_quality.json",
    "equity_curve.json",
    "balance_curve.json",
    "drawdown_curve.json",
    "trade_sequence.json",
    "hybrid_exit_statistics.json",
    "performance_metrics.json",
    "phase28d_final_report.json",
]

VERDICTS = {"PROFITABLE", "NOT_PROFITABLE"}


class TestPhase28DDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase28d_final_report.json").is_file():
            raise unittest.SkipTest("Phase 28D deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase28d_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)
        self.assertEqual(report.get("initial_balance"), 200.0)

    def test_hybrid_b_exit_mode(self) -> None:
        report = json.loads((PHASE_DIR / "phase28d_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report.get("exit_mode"), "HYBRID_B")
        self.assertTrue(report.get("fresh_backtest"))

    def test_trade_log(self) -> None:
        tl = json.loads((PHASE_DIR / "trade_log.json").read_text(encoding="utf-8"))
        self.assertGreater(tl.get("trade_count", 0), 0)

    def test_performance_metrics(self) -> None:
        pm = json.loads((PHASE_DIR / "performance_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(pm.get("initial_balance"), 200.0)
        self.assertIn("final_balance", pm)

    def test_equity_curve(self) -> None:
        eq = json.loads((PHASE_DIR / "equity_curve.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(eq.get("curve") or []), 2)

    def test_hybrid_exit_stats(self) -> None:
        he = json.loads((PHASE_DIR / "hybrid_exit_statistics.json").read_text(encoding="utf-8"))
        self.assertIn("exit_counts", he)


if __name__ == "__main__":
    unittest.main()
