"""Phase 35 — label alignment tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase35Alignment(unittest.TestCase):
    def test_resolve_label_buy_tp(self) -> None:
        from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp

        candles = pd.DataFrame({
            "open": [100, 101, 102, 103],
            "high": [101, 102, 110, 104],
            "low": [99, 100, 101, 102],
            "close": [100.5, 101.5, 109, 103.5],
        })
        r = resolve_label_with_sl_tp(candles, 0, 1, 98.0, 106.0, future_window_bars=3)
        self.assertEqual(r["label"], 1)
        self.assertTrue(r["tp_hit"])

    def test_resolve_label_sell_sl(self) -> None:
        from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp

        candles = pd.DataFrame({
            "open": [100, 99, 98],
            "high": [101, 103, 99],
            "low": [99, 98, 97],
            "close": [100, 99, 98],
        })
        r = resolve_label_with_sl_tp(candles, 0, -1, 102.0, 96.0, future_window_bars=2)
        self.assertEqual(r["label"], 0)
        self.assertTrue(r["sl_hit"])

    def test_sl_tp_distance_metrics(self) -> None:
        from tradingbot.ml.research.phase35.label_alignment import sl_tp_distance_metrics

        m = sl_tp_distance_metrics(100.0, 1, 98.0, 104.0, 97.0, 107.5)
        self.assertGreater(m["rr_dataset"], 0)
        self.assertGreater(m["rr_production"], 0)

    def test_deliverables_after_run(self) -> None:
        report = PROJECT_ROOT / "phase35_final_report.json"
        if not report.exists():
            self.skipTest("phase35 not yet run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "35")
        self.assertIn(data["verdict"], {
            "LABELS_ALIGNABLE", "LABELS_PARTIALLY_ALIGNABLE",
            "LABELS_MISALIGNED", "LABELS_NEEDS_REVIEW", "INSUFFICIENT_DATA",
        })
        self.assertGreaterEqual(data.get("candle_coverage", {}).get("coverage_pct", 0), 0)


if __name__ == "__main__":
    unittest.main()
