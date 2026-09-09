"""Phase 22Y — accepted candidate failure forensics tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22YForensics(unittest.TestCase):
    def test_gate_passed_candidates_all_fail_overfitting_rule(self):
        from tradingbot.ml.research.phase22y.acceptance_forensics import run_forensics

        comparison_path = ROOT / "data" / "ml" / "reports" / "phase9_9_model_comparison.json"
        if not comparison_path.is_file():
            self.skipTest("phase9_9_model_comparison.json missing")

        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        result = run_forensics(comparison)
        dominant = result["dominant_rejection_rule"]

        self.assertEqual(result["accepted_candidates"]["count"], 5)
        self.assertEqual(dominant["rule"], "robustness_improved")
        self.assertEqual(dominant["failed_count"], 4)
        self.assertFalse(dominant["all_five_gate_passed_candidates_fail_this_rule"])

    def test_single_rule_relaxation_accepts_one_candidate(self):
        from tradingbot.ml.research.phase22y.acceptance_forensics import run_forensics

        comparison_path = ROOT / "data" / "ml" / "reports" / "phase9_9_model_comparison.json"
        if not comparison_path.is_file():
            self.skipTest("phase9_9_model_comparison.json missing")

        result = run_forensics(json.loads(comparison_path.read_text(encoding="utf-8")))
        best = result["candidate_acceptance_simulation"]["probability_gate_passed_only"][
            "best_single_rule_relaxation"
        ]
        self.assertEqual(best["ignored_rule"], "robustness_improved")
        self.assertEqual(best["accepted_count"], 3)


class TestPhase22YDeliverables(unittest.TestCase):
    def test_deliverables_and_verdict(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22y"
        for name in (
            "accepted_candidates.json",
            "acceptance_breakdown.json",
            "rule_failure_statistics.json",
            "dominant_rejection_rule.json",
            "rule_origin_analysis.json",
            "candidate_acceptance_simulation.json",
            "phase22y_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22y run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22y_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "ACCEPTANCE_RULE_TOO_STRICT")


if __name__ == "__main__":
    unittest.main()
