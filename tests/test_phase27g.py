"""Phase 27G — trade performance validation deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27g"

DELIVERABLES = [
    "trade_statistics.json",
    "profitability_report.json",
    "direction_analysis.json",
    "regime_analysis.json",
    "engine_analysis.json",
    "confidence_analysis.json",
    "time_analysis.json",
    "risk_analysis.json",
    "exit_analysis.json",
    "equity_curve.json",
    "drawdown_curve.json",
    "final_report.json",
]

VERDICTS = {"PERFORMANCE_VALIDATED", "PERFORMANCE_NOT_VALIDATED"}
MINIMUM_SAMPLE = 200


class TestPhase27GDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "final_report.json").is_file():
            raise unittest.SkipTest("Phase 27G deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_minimum_sample(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(report.get("completed_trades", 0), MINIMUM_SAMPLE)
        self.assertTrue(report.get("sample_sufficient"))

    def test_trade_statistics_complete(self) -> None:
        stats = json.loads((PHASE_DIR / "trade_statistics.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(stats.get("total_trades", 0), MINIMUM_SAMPLE)
        self.assertIn("win_rate_pct", stats)
        self.assertIn("trades_per_day", stats)

    def test_profitability_metrics(self) -> None:
        prof = json.loads((PHASE_DIR / "profitability_report.json").read_text(encoding="utf-8"))
        for key in ("profit_factor", "expectancy", "sharpe_ratio", "maximum_drawdown_pct"):
            self.assertIn(key, prof)

    def test_confidence_buckets(self) -> None:
        conf = json.loads((PHASE_DIR / "confidence_analysis.json").read_text(encoding="utf-8"))
        buckets = conf.get("buckets") or {}
        expected = {"0.50-0.60", "0.60-0.70", "0.70-0.80", "0.80-0.90", "0.90-1.00"}
        self.assertTrue(expected.issubset(set(buckets.keys())))

    def test_exit_reasons_cover_trades(self) -> None:
        stats = json.loads((PHASE_DIR / "trade_statistics.json").read_text(encoding="utf-8"))
        exit_a = json.loads((PHASE_DIR / "exit_analysis.json").read_text(encoding="utf-8"))
        total = stats.get("total_trades", 0)
        classified = exit_a.get("sl_count", 0) + exit_a.get("tp_count", 0) + exit_a.get("timeout_count", 0)
        self.assertEqual(classified, total)

    def test_equity_curve_points(self) -> None:
        eq = json.loads((PHASE_DIR / "equity_curve.json").read_text(encoding="utf-8"))
        points = eq.get("points") or []
        self.assertGreater(len(points), MINIMUM_SAMPLE)


if __name__ == "__main__":
    unittest.main()
