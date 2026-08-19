"""Phase 39 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase39(unittest.TestCase):
    def test_discover_sources_returns_list(self) -> None:
        from tradingbot.ml.research.phase39.candle_sources import discover_candle_sources

        sources = discover_candle_sources()
        self.assertIsInstance(sources, list)

    def test_fast_sl_tp_parity(self) -> None:
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.research.phase35.label_alignment import production_sl_tp_at_bar
        from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast

        candles = CandleStore(None).load("XAUUSD", "M5")
        if candles is None or candles.empty:
            self.skipTest("no candles")
        candles.index = pd.to_datetime(candles.index, utc=True)
        idx = min(50000, len(candles) - 100)
        full = production_sl_tp_at_bar(candles, idx, 1)
        fast = production_sl_tp_at_bar_fast(candles, idx, 1)
        self.assertAlmostEqual(full[0], fast[0], places=4)
        self.assertAlmostEqual(full[1], fast[1], places=4)

    def test_vectorized_bar_indices(self) -> None:
        from tradingbot.ml.research.phase39.expand_dataset import vectorized_bar_indices

        candles = pd.DataFrame(
            {"close": range(50)},
            index=pd.date_range("2025-01-01", periods=50, freq="5min", tz="UTC"),
        )
        ts = pd.Series([candles.index[10], candles.index[25]])
        idx = vectorized_bar_indices(candles, ts)
        self.assertEqual(int(idx[0]), 10)
        self.assertEqual(int(idx[1]), 25)

    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase39_final_report.json"
        if not report.exists():
            self.skipTest("phase39 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "39")
        self.assertGreater(data.get("dataset_v3_expanded_rows", 0), 1500)


if __name__ == "__main__":
    unittest.main()
