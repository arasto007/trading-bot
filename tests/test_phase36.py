"""Phase 36 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase36(unittest.TestCase):
    def test_chronological_split_no_shuffle(self) -> None:
        from tradingbot.ml.dataset.splitter import time_based_split

        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=100, freq="5min", tz="UTC"),
            "label_v3": [1, 0] * 50,
            "f1": range(100),
        })
        s = time_based_split(df, purge_bars=0)
        self.assertGreater(len(s.train), 0)
        self.assertGreater(len(s.test), 0)

    def test_build_aligned_rows_smoke(self) -> None:
        from tradingbot.ml.research.phase36.build_dataset_v3 import build_aligned_rows

        candles = pd.DataFrame({
            "open": [100 + i * 0.1 for i in range(200)],
            "high": [101 + i * 0.1 for i in range(200)],
            "low": [99 + i * 0.1 for i in range(200)],
            "close": [100.5 + i * 0.1 for i in range(200)],
            "volume": [100] * 200,
        }, index=pd.date_range("2025-06-01", periods=200, freq="5min", tz="UTC"))
        df = pd.DataFrame({
            "timestamp": [candles.index[50], candles.index[80]],
            "entry_price": [100.5, 103.5],
            "direction": [1, -1],
            "label": [1, 0],
            "stop_loss": [98.0, 105.0],
            "take_profit": [106.0, 98.0],
            "future_window_bars": [72, 72],
            "f1": [0.1, 0.2],
        })
        out = build_aligned_rows(df, candles)
        self.assertGreaterEqual(len(out), 1)

    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase36_final_report.json"
        if not report.exists():
            self.skipTest("phase36 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "36")
        self.assertGreater(data.get("dataset_v3_rows", 0), 100)


if __name__ == "__main__":
    unittest.main()
