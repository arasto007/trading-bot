"""Phase 45 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase45(unittest.TestCase):
    def test_filter_structure_rows(self) -> None:
        from tradingbot.ml.research.phase45.structure_dataset import filter_structure_rows

        df = pd.DataFrame({
            "event_type": ["session_transition", "trading_session", "choch"],
            "label_v3": [1, 0, 1],
            "timestamp": pd.date_range("2025-01-01", periods=3, freq="5min", tz="UTC"),
        })
        out = filter_structure_rows(df)
        self.assertEqual(len(out), 2)

    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase45_final_report.json"
        if not report.exists():
            self.skipTest("phase45 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertGreater(data.get("dataset_v5_rows", 0), 100)


if __name__ == "__main__":
    unittest.main()
