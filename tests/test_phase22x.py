"""Phase 22X — probability selection gate tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.robustness_optimizer.candidate_selector import rank_candidates, select_best
from tradingbot.ml.research.robustness_optimizer.probability_selection_gate import (
    BUY_THRESHOLD,
    SELL_THRESHOLD,
    compute_probability_metrics,
    evaluate_probability_gate,
)
from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance


def _base_experiment(**overrides) -> dict:
    exp = {
        "robustness_score": 80.0,
        "mean_profit_factor": 1.4,
        "mean_expectancy": 0.2,
        "mean_auc_gap": 0.03,
        "aggregate": {"stability_score": {"std_expectancy": 0.05}},
        "robustness": {"overfitting_indicators": {}},
        "profitable_windows": 5,
        "window_count": 5,
        "overfitting_risk": "LOW",
        "candidate_id": "test",
        "experiment_id": "test__RANGE",
    }
    exp.update(overrides)
    return exp


class TestProbabilitySelectionGate(unittest.TestCase):
    def test_sell_only_model_rejected(self):
        probs = np.full(200, 0.35)
        metrics = compute_probability_metrics(probs)
        gate = evaluate_probability_gate(metrics)

        self.assertEqual(metrics["buy_coverage_pct"], 0.0)
        self.assertGreater(metrics["sell_coverage_pct"], 0.0)
        self.assertFalse(gate["passed"])
        self.assertIn("buy_coverage_zero", gate["rejection_reasons"])
        self.assertIn("max_probability_below_buy_threshold", gate["rejection_reasons"])

    def test_buy_only_model_rejected(self):
        probs = np.full(200, 0.70)
        metrics = compute_probability_metrics(probs)
        gate = evaluate_probability_gate(metrics)

        self.assertEqual(metrics["sell_coverage_pct"], 0.0)
        self.assertGreater(metrics["buy_coverage_pct"], 0.0)
        self.assertFalse(gate["passed"])
        self.assertIn("sell_coverage_zero", gate["rejection_reasons"])
        self.assertIn("min_probability_above_sell_threshold", gate["rejection_reasons"])

    def test_collapsed_probability_model_rejected(self):
        probs = np.full(200, 0.50)
        metrics = compute_probability_metrics(probs)
        gate = evaluate_probability_gate(metrics)

        self.assertFalse(gate["passed"])
        self.assertIn("probability_distribution_collapsed", gate["rejection_reasons"])

    def test_normal_probability_distribution_passes(self):
        probs = np.linspace(0.35, 0.65, 200)
        metrics = compute_probability_metrics(probs)
        gate = evaluate_probability_gate(metrics)

        self.assertGreater(metrics["buy_coverage_pct"], 0.0)
        self.assertGreater(metrics["sell_coverage_pct"], 0.0)
        self.assertGreaterEqual(metrics["max_probability"], BUY_THRESHOLD)
        self.assertLessEqual(metrics["min_probability"], SELL_THRESHOLD)
        self.assertGreaterEqual(metrics["std"], 0.015)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["acceptance_reason"], "probability_quality_passed")

    def test_select_best_skips_failed_probability_gate(self):
        good_metrics = compute_probability_metrics(np.linspace(0.35, 0.65, 100))
        bad_metrics = compute_probability_metrics(np.full(100, 0.35))

        experiments = [
            _base_experiment(
                experiment_id="bad_pf_high",
                candidate_id="bad",
                mean_profit_factor=2.0,
                robustness_score=90.0,
                probability_metrics=bad_metrics,
                probability_gate=evaluate_probability_gate(bad_metrics),
            ),
            _base_experiment(
                experiment_id="good",
                candidate_id="good",
                mean_profit_factor=1.2,
                robustness_score=70.0,
                probability_metrics=good_metrics,
                probability_gate=evaluate_probability_gate(good_metrics),
            ),
        ]
        ranked = rank_candidates(experiments)
        best = select_best(ranked)

        self.assertIsNotNone(best)
        self.assertEqual(best["candidate_id"], "good")
        self.assertTrue(best["probability_gate_passed"])

    def test_acceptance_requires_probability_quality(self):
        metrics = compute_probability_metrics(np.full(100, 0.35))
        gate = evaluate_probability_gate(metrics)
        best = {
            "robustness_score": 80.0,
            "overfitting_risk": "LOW",
            "mean_expectancy": 0.2,
            "profitable_windows": 5,
            "window_count": 5,
            "probability_gate_passed": gate["passed"],
            "acceptance_reason": gate["acceptance_reason"],
            "rejection_reason": gate["rejection_reason"],
            "buy_coverage_pct": metrics["buy_coverage_pct"],
            "sell_coverage_pct": metrics["sell_coverage_pct"],
            "probability_std": metrics["std"],
        }
        acceptance = evaluate_acceptance(
            best,
            {"robustness_score": 50.0, "overfitting_risk": "HIGH"},
        )
        self.assertFalse(acceptance["checks"]["probability_quality_passed"])
        self.assertEqual(acceptance["final_verdict"], "FAIL")


class TestPhase22XDeliverables(unittest.TestCase):
    def test_deliverables_exist_after_investigation(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22x"
        for name in (
            "selection_gate_validation.json",
            "candidate_probability_metrics.json",
            "candidate_acceptance_report.json",
            "training_pipeline_validation.json",
            "phase22x_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22x run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22x_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "SELECTION_PIPELINE_FIXED")


if __name__ == "__main__":
    unittest.main()
