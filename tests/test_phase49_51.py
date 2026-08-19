"""Phase 49-51 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase49(unittest.TestCase):
    def test_resolve_bar_index(self) -> None:
        from tradingbot.ml.research.phase49.bar_index import resolve_bar_index

        candles = pd.DataFrame(
            {"close": range(100)},
            index=pd.date_range("2025-01-01", periods=100, freq="5min", tz="UTC"),
        )
        ts = candles.index[42]
        self.assertEqual(resolve_bar_index(candles, ts), 42)

    def test_quarter_labels(self) -> None:
        from tradingbot.ml.research.phase49.historical_windows import quarter_labels

        labels = quarter_labels(2021, 2022)
        self.assertIn("Y2021Q1", labels)
        self.assertIn("Y2022Q4", labels)


class TestPhase50(unittest.TestCase):
    def test_strict_gate_requires_windows(self) -> None:
        from tradingbot.ml.research.phase50.strict_walk_forward import strict_walk_forward

        rows = []
        for year in (2022, 2023, 2024, 2025):
            for i in range(150):
                rows.append({
                    "timestamp": pd.Timestamp(f"{year}-06-15", tz="UTC") + pd.Timedelta(minutes=5 * i),
                    "label_v3": i % 2,
                    "f1": float(i) * 0.01,
                    "f2": float(i) * 0.02,
                })
        df = pd.DataFrame(rows)
        res = strict_walk_forward(df, "label_v3", ["f1", "f2"], min_test_trades=5)
        self.assertIn("walk_forward_windows", res)


class TestPhase51(unittest.TestCase):
    def test_proximity_score(self) -> None:
        from tradingbot.ml.research.phase51.profitability_score import profitability_proximity

        p = profitability_proximity(
            strict_gate_passed=True,
            mean_pf=1.35,
            mean_auc=0.58,
            windows_count=4,
            windows_pf_above_1_3=3,
            v7_rows=9000,
        )
        self.assertGreaterEqual(p["proximity_score"], 60)


class TestDeliverables(unittest.TestCase):
    def test_phase49_report(self) -> None:
        p = PROJECT_ROOT / "phase49_final_report.json"
        if not p.exists():
            self.skipTest("phase49 not run")
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "49")


if __name__ == "__main__":
    unittest.main()
