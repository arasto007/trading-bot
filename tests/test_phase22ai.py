"""Phase 22AI — acceptance patch and freeze bridge prototype tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.robustness_optimizer.freeze_bridge import (
    FreezeBridgeError,
    build_freeze_contract,
    validate_accepted_candidate,
)
from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance


def _baseline(**overrides) -> dict:
    base = {
        "robustness_score": 66.57,
        "overfitting_risk": "HIGH",
        "mean_auc_gap": 0.3308,
    }
    base.update(overrides)
    return base


def _candidate(**overrides) -> dict:
    cand = {
        "experiment_id": "xgb_baseline_phase96__stable_except_unstable__RANGE",
        "candidate_id": "xgb_baseline_phase96",
        "model_name": "xgboost",
        "feature_subset": "stable_except_unstable",
        "regime": "RANGE",
        "robustness_score": 70.0,
        "overfitting_risk": "HIGH",
        "mean_profit_factor": 1.31,
        "mean_expectancy": 0.17,
        "mean_auc_gap": 0.3195,
        "profitable_windows": 4,
        "window_count": 5,
        "composite_score": 0.58,
        "probability_gate_passed": True,
        "buy_coverage_pct": 10.0,
        "sell_coverage_pct": 70.0,
        "probability_std": 0.16,
        "min_probability": 0.05,
        "max_probability": 0.89,
    }
    cand.update(overrides)
    return cand


FEATURE_SUBSETS = {
    "stable_except_unstable": ["ema50_slope", "candle_direction", "structure_distance"],
}


class TestAcceptancePatch(unittest.TestCase):
    def test_numeric_gap_pass(self):
        acceptance = evaluate_acceptance(_candidate(), _baseline())
        self.assertTrue(acceptance["checks"]["overfitting_risk_decreased"])
        self.assertEqual(acceptance["final_verdict"], "PASS")

    def test_numeric_gap_fail_when_gap_not_lower(self):
        acceptance = evaluate_acceptance(_candidate(mean_auc_gap=0.35), _baseline())
        self.assertFalse(acceptance["checks"]["overfitting_risk_decreased"])

    def test_missing_candidate_gap_rejected_fail_closed(self):
        acceptance = evaluate_acceptance(_candidate(mean_auc_gap=None), _baseline())
        self.assertFalse(acceptance["checks"]["overfitting_risk_decreased"])
        self.assertIsNone(acceptance["best_mean_auc_gap"])

    def test_missing_baseline_gap_rejected_fail_closed(self):
        acceptance = evaluate_acceptance(_candidate(), _baseline(mean_auc_gap=None))
        self.assertFalse(acceptance["checks"]["overfitting_risk_decreased"])
        self.assertIsNone(acceptance["baseline_mean_auc_gap"])

    def test_probability_gate_rejection(self):
        acceptance = evaluate_acceptance(
            _candidate(probability_gate_passed=False, buy_coverage_pct=0.0),
            _baseline(),
        )
        self.assertFalse(acceptance["checks"]["probability_quality_passed"])
        self.assertEqual(acceptance["final_verdict"], "FAIL")


class TestFreezeBridge(unittest.TestCase):
    def test_invalid_candidate_rejection(self):
        acceptance = evaluate_acceptance(_candidate(), _baseline())
        errors = validate_accepted_candidate(
            _candidate(candidate_id="unknown_model"),
            acceptance,
            feature_subsets=FEATURE_SUBSETS,
        )
        self.assertIn("unknown_candidate", errors)

    def test_missing_acceptance_rejection(self):
        errors = validate_accepted_candidate(
            _candidate(),
            {"final_verdict": "FAIL", "checks": {}},
            feature_subsets=FEATURE_SUBSETS,
        )
        self.assertIn("missing_acceptance_pass", errors)

    def test_freeze_contract_validation(self):
        candidate = _candidate()
        acceptance = evaluate_acceptance(candidate, _baseline())
        contract = build_freeze_contract(
            candidate,
            acceptance,
            feature_subsets=FEATURE_SUBSETS,
        )
        self.assertEqual(contract["candidate_id"], "xgb_baseline_phase96")
        self.assertEqual(contract["model_type"], "xgboost")
        self.assertTrue(contract["metadata"]["artifact_write"])
        self.assertEqual(contract["acceptance_status"]["final_verdict"], "PASS")

    def test_freeze_contract_rejects_fail_acceptance(self):
        with self.assertRaises(FreezeBridgeError):
            build_freeze_contract(
                _candidate(),
                {"final_verdict": "FAIL", "checks": {"probability_quality_passed": False}},
                feature_subsets=FEATURE_SUBSETS,
            )


class TestPhase22AIRegression(unittest.TestCase):
    def test_expected_candidate_passes_regression(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ai.acceptance_regression import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertTrue(result["candidate_before_after"]["expected_new_pass_met"])
        self.assertEqual(result["verdict"], "READY_FOR_PRODUCTION_FREEZE_WIRING")

    def test_authority_chain_has_no_default_config(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ai.acceptance_regression import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        authority = result["authority_check"]
        self.assertFalse(authority["uses_default_config"])
        self.assertFalse(authority["hardcodes_logistic_strong_reg"])
        self.assertTrue(authority["authority_chain_valid"])


class TestPhase22AIDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22ai"
        for name in (
            "acceptance_patch_diff.json",
            "candidate_before_after.json",
            "freeze_contract_validation.json",
            "authority_check.json",
            "phase22ai_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22ai run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22ai_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "READY_FOR_PRODUCTION_FREEZE_WIRING")
        self.assertFalse(final["production_modified"])


if __name__ == "__main__":
    unittest.main()
