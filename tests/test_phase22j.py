"""Phase 22J tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase22j.engine_candidates import list_engine_candidates, top_five_engine_candidates
from tradingbot.ml.research.phase22j.selection import compare_engine_candidates


class TestPhase22J(unittest.TestCase):
    def setUp(self):
        os.environ["USE_ML_KERNEL"] = "true"
        os.environ["TREND_MODEL_VERSION"] = "v41"

    def test_five_engine_candidates(self):
        self.assertEqual(len(top_five_engine_candidates()), 5)

    def test_no_threshold_tuning(self):
        for c in top_five_engine_candidates():
            self.assertFalse(c.threshold_tuning)

    def test_compare_ranks_pf(self):
        r = compare_engine_candidates([
            {"candidate_id": "22J-BASELINE", "profit_factor": 0.5, "trades": 2},
            {"candidate_id": "22J-003", "profit_factor": 0.8, "trades": 4},
        ])
        self.assertEqual(r["best_by_pf"], "22J-003")


if __name__ == "__main__":
    unittest.main()
