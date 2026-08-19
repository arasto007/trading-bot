"""Phase 34A — raw ML truth audit unit tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERDICTS = {
    "ML_IS_EXCELLENT",
    "ML_IS_GOOD",
    "ML_IS_AVERAGE",
    "ML_IS_WEAK",
    "ML_IS_UNUSABLE",
}


class TestPhase34AMetrics(unittest.TestCase):
    def test_stats_from_replays_deterministic(self) -> None:
        from tradingbot.ml.research.phase34a.metrics import stats_from_replays

        replays = [
            {"r_multiple": 2.0, "bars_to_tp": 10},
            {"r_multiple": -1.0, "bars_to_sl": 5},
            {"r_multiple": 1.5, "bars_to_tp": 20},
        ]
        a = stats_from_replays(replays)
        b = stats_from_replays(replays)
        self.assertEqual(a, b)
        self.assertEqual(a["trade_count"], 3)
        self.assertEqual(a["wins"], 2)
        self.assertEqual(a["losses"], 1)

    def test_classify_ml_quality_buckets(self) -> None:
        from tradingbot.ml.research.phase34a.metrics import classify_ml_quality

        self.assertEqual(
            classify_ml_quality({"trade_count": 50, "profit_factor": 1.6, "win_rate_pct": 56, "expectancy_r": 0.2}),
            "ML_IS_EXCELLENT",
        )
        self.assertEqual(
            classify_ml_quality({"trade_count": 50, "profit_factor": 0.7, "win_rate_pct": 40, "expectancy_r": -0.1}),
            "ML_IS_UNUSABLE",
        )
        self.assertEqual(classify_ml_quality({"trade_count": 5}), "UNUSABLE")

    def test_infer_kernel_direction(self) -> None:
        from tradingbot.ml.research.phase34a.collector import _infer_kernel_direction

        self.assertEqual(_infer_kernel_direction("BUY", True, True, True), "BUY")
        self.assertEqual(_infer_kernel_direction("SELL", True, False, None), "HOLD")
        self.assertEqual(_infer_kernel_direction("BUY", True, True, False), "HOLD")
        self.assertEqual(_infer_kernel_direction("HOLD", True, True, True), "HOLD")

    def test_confidence_bucket(self) -> None:
        from tradingbot.ml.research.phase34a.metrics import confidence_bucket

        self.assertEqual(confidence_bucket(0.35), "<0.40")
        self.assertEqual(confidence_bucket(0.52), "0.50-0.55")
        self.assertEqual(confidence_bucket(0.97), "0.95-1.00")


class TestPhase34ADeliverables(unittest.TestCase):
    def test_final_report_exists_after_run(self) -> None:
        report = PROJECT_ROOT / "phase34a_final_report.json"
        if not report.exists():
            self.skipTest("phase34a not yet run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "34A")
        self.assertIn(data["verdict"], VERDICTS)
        self.assertGreaterEqual(data["raw_ml_statistics"]["trade_count"], 50)


if __name__ == "__main__":
    unittest.main()
