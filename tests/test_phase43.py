"""Phase 43 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase43(unittest.TestCase):
    def test_build_subsets(self) -> None:
        from tradingbot.ml.research.phase43.subset_builder import build_subsets

        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=200, freq="5min", tz="UTC"),
            "event_type": ["session_transition"] * 170 + ["trading_session"] * 30,
            "label_v3": [1, 0] * 100,
        })
        subs = build_subsets(df)
        self.assertIn("v4_balanced", subs)
        self.assertLessEqual(len(subs["v4_balanced"]), len(subs["v3_full"]))

    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase43_final_report.json"
        if not report.exists():
            self.skipTest("phase43 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertIn("best_subset", data)


if __name__ == "__main__":
    unittest.main()
