"""Phase 46 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase46(unittest.TestCase):
    def test_build_historical_dataset(self) -> None:
        from tradingbot.ml.research.phase46.ml_signal_dataset import build_historical_dataset

        ds = build_historical_dataset(30)
        self.assertEqual(ds.label, "H")
        self.assertEqual(ds.trading_days, 30)

    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase46_final_report.json"
        if not report.exists():
            self.skipTest("phase46 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertIn("dataset_v6_rows", data)


if __name__ == "__main__":
    unittest.main()
