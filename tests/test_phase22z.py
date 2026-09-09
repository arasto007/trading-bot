"""Phase 22Z — overfitting rule validation tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22ZValidation(unittest.TestCase):
    def test_label_logic_dominates_overfitting_failures(self):
        from tradingbot.ml.research.phase22z.overfitting_rule_validation import run_validation

        comparison = json.loads(
            (ROOT / "data" / "ml" / "reports" / "phase9_9_model_comparison.json").read_text(encoding="utf-8")
        )
        rob98 = json.loads(
            (ROOT / "data" / "ml" / "reports" / "phase9_8_robustness_report.json").read_text(encoding="utf-8")
        )
        win98 = json.loads(
            (ROOT / "data" / "ml" / "reports" / "phase9_8_window_results.json").read_text(encoding="utf-8")
        )
        result = run_validation(comparison, phase98_robustness=rob98, phase98_windows=win98)
        stats = result["rule_correctness_report"]["statistics"]

        self.assertEqual(stats["total_candidates"], 28)
        self.assertEqual(stats["fail_really_overfit"], 1)
        self.assertEqual(stats["fail_label_logic"], 0)
        self.assertGreaterEqual(stats["fail_really_overfit"], stats["fail_label_logic"])
        self.assertEqual(stats["numeric_mean_auc_gap_better_than_baseline"], 27)

    def test_gate_passed_candidates_fail_ordinal_overfitting(self):
        from tradingbot.ml.research.phase22z.overfitting_rule_validation import run_validation

        comparison = json.loads(
            (ROOT / "data" / "ml" / "reports" / "phase9_9_model_comparison.json").read_text(encoding="utf-8")
        )
        rob98 = json.loads(
            (ROOT / "data" / "ml" / "reports" / "phase9_8_robustness_report.json").read_text(encoding="utf-8")
        )
        win98 = json.loads(
            (ROOT / "data" / "ml" / "reports" / "phase9_8_window_results.json").read_text(encoding="utf-8")
        )
        result = run_validation(comparison, phase98_robustness=rob98, phase98_windows=win98)
        self.assertEqual(
            result["rule_correctness_report"]["statistics"]["probability_gate_passed_fail_overfitting_ordinal"],
            1,
        )


class TestPhase22ZDeliverables(unittest.TestCase):
    def test_deliverables_and_verdict(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22z"
        for name in (
            "candidate_overfitting_metrics.json",
            "baseline_comparison.json",
            "overfitting_numeric_analysis.json",
            "rule_correctness_report.json",
            "candidate_rejection_reason.json",
            "phase22z_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22z run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22z_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "RULE_TOO_STRICT")


if __name__ == "__main__":
    unittest.main()
