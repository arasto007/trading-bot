"""Phase 40 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase40(unittest.TestCase):
    def test_threshold_sweep(self) -> None:
        from tradingbot.ml.research.phase40.retrain_sweep import sweep_thresholds

        y = np.array([1, 0, 1, 0, 1])
        proba = np.array([0.9, 0.2, 0.7, 0.4, 0.6])
        sweep = sweep_thresholds(y, proba, [0.5, 0.6])
        self.assertEqual(len(sweep), 2)
        self.assertIn("pf", sweep[0])

    def test_walk_forward_smoke(self) -> None:
        from tradingbot.ml.research.phase40.retrain_sweep import walk_forward_retrain

        rows = []
        for year in (2024, 2025, 2026):
            for i in range(60):
                rows.append({
                    "timestamp": pd.Timestamp(f"{year}-06-15 12:00:00", tz="UTC") + pd.Timedelta(minutes=5 * i),
                    "label_v3": i % 2,
                    "f1": float(i) * 0.01,
                    "f2": float(i) * 0.02,
                })
        df = pd.DataFrame(rows)
        res = walk_forward_retrain(df, "label_v3", ["f1", "f2"], model_name="random_forest")
        self.assertIn("walk_forward_windows", res)

    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase40_final_report.json"
        if not report.exists():
            self.skipTest("phase40 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "40")
        self.assertIn("best_model", data)


if __name__ == "__main__":
    unittest.main()
