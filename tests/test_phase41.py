"""Phase 41 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase41(unittest.TestCase):
    def test_per_year_label_stats(self) -> None:
        from tradingbot.ml.research.phase41.model_search import per_year_label_stats

        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=40, freq="5min", tz="UTC"),
            "label_v3": [1, 0] * 20,
        })
        stats = per_year_label_stats(df)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["year"], 2024)

    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase41_final_report.json"
        if not report.exists():
            self.skipTest("phase41 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "41")
        self.assertIn("integration_gate", data)


if __name__ == "__main__":
    unittest.main()
