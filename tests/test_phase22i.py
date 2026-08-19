"""Phase 22I — decision engine research tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.decision_engine.decision_policy import DecisionPolicy
from tradingbot.ml.research.phase22i.candidates import list_policy_candidates, top_five_candidates
from tradingbot.ml.research.phase22i.selection import compare_candidates


class TestPhase22I(unittest.TestCase):
    def setUp(self):
        os.environ["USE_ML_KERNEL"] = "true"
        os.environ["TREND_MODEL_VERSION"] = "v41"

    def test_five_candidates_defined(self):
        policy = DecisionPolicy(min_confidence=0.48)
        top = top_five_candidates(policy=policy)
        self.assertEqual(len(top), 5)
        self.assertTrue(all(not c.threshold_tuning for c in top))

    def test_compare_candidates_ranks_by_pf(self):
        results = [
            {"candidate_id": "22I-BASELINE", "profit_factor": 0.5, "expectancy": -1, "trades": 2},
            {"candidate_id": "22I-001", "profit_factor": 0.8, "expectancy": 0.1, "trades": 5},
        ]
        cmp = compare_candidates(results)
        self.assertEqual(cmp["best_candidate_id"], "22I-001")

    def test_baseline_in_catalog(self):
        policy = DecisionPolicy(min_confidence=0.48)
        ids = [c.id for c in list_policy_candidates(policy=policy)]
        self.assertIn("22I-BASELINE", ids)
        self.assertIn("22I-003", ids)


if __name__ == "__main__":
    unittest.main()
