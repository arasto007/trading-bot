"""Phase 22AJ — production freeze authority wiring tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import phase9_9_freeze_manifest_path, phase9_9_metadata_path
from tradingbot.ml.paper_trading.model_registry import (
    FreezeContractRequiredError,
    build_test_freeze_contract,
    freeze_phase9_9_artifacts,
    validate_freeze_contract,
)
from tradingbot.ml.research.robustness_optimizer.candidate_selector import (
    select_best,
    select_production_winner,
)
from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance


def _baseline(**overrides) -> dict:
    base = {"robustness_score": 66.57, "overfitting_risk": "HIGH", "mean_auc_gap": 0.3308}
    base.update(overrides)
    return base


def _candidate(**overrides) -> dict:
    cand = {
        "experiment_id": "xgb_baseline_phase96__stable_except_unstable__RANGE",
        "candidate_id": "xgb_baseline_phase96",
        "model_name": "xgboost",
        "feature_subset": "stable_except_unstable",
        "robustness_score": 70.0,
        "overfitting_risk": "HIGH",
        "mean_profit_factor": 1.31,
        "mean_expectancy": 0.17,
        "mean_auc_gap": 0.3195,
        "profitable_windows": 4,
        "window_count": 5,
        "composite_score": 0.592035,
        "probability_gate_passed": True,
        "buy_coverage_pct": 10.0,
        "sell_coverage_pct": 70.0,
        "probability_std": 0.16,
        "min_probability": 0.05,
        "max_probability": 0.89,
    }
    cand.update(overrides)
    return cand


class TestPhase22AJWiring(unittest.TestCase):
    def test_select_production_winner_returns_accepted_candidate(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir, phase9_9_model_comparison_path

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        comparison = json.loads(phase9_9_model_comparison_path(base_dir).read_text(encoding="utf-8"))
        ranked = comparison["ranked_candidates"]
        baseline = _baseline()
        winner = select_production_winner(ranked, baseline)
        self.assertIsNotNone(winner)
        acceptance = evaluate_acceptance(winner, baseline)
        self.assertEqual(acceptance["final_verdict"], "PASS")
        self.assertEqual(winner["experiment_id"], "xgb_baseline_phase96__stable_except_unstable__RANGE")

    def test_rejected_rank_one_cannot_freeze(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir, phase9_9_model_comparison_path

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        ranked = json.loads(phase9_9_model_comparison_path(base_dir).read_text())["ranked_candidates"]
        baseline = _baseline()
        rank_one = ranked[0]
        self.assertEqual(rank_one["experiment_id"], select_best(ranked)["experiment_id"])
        self.assertEqual(evaluate_acceptance(rank_one, baseline)["final_verdict"], "FAIL")
        contract = build_test_freeze_contract()
        contract["acceptance_status"] = {"final_verdict": "FAIL", "checks": {}}
        self.assertIn("acceptance_not_pass", validate_freeze_contract(contract))

    def test_logistic_default_config_cannot_freeze_without_contract(self):
        import pandas as pd

        df = pd.DataFrame({"label": [0, 1] * 30})
        with self.assertRaises(FreezeContractRequiredError):
            freeze_phase9_9_artifacts(df, contract=None)

    def test_missing_acceptance_fails_closed(self):
        contract = build_test_freeze_contract()
        contract["acceptance_status"] = {"final_verdict": "FAIL", "checks": {}}
        self.assertIn("acceptance_not_pass", validate_freeze_contract(contract))

    def test_invalid_contract_rejected(self):
        contract = build_test_freeze_contract()
        contract["candidate_id"] = "unknown_model_xyz"
        self.assertIn("unknown_candidate", validate_freeze_contract(contract))

    def test_manifest_generated_on_freeze(self):
        from tests.test_ml_paper_phase9_10 import _setup_paper

        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            from tradingbot.ml.dataset.store import DatasetStore

            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            contract = build_test_freeze_contract()
            freeze_phase9_9_artifacts(df, contract=contract, base_dir=tmp)
            self.assertTrue(phase9_9_freeze_manifest_path(tmp).is_file())
            metadata = json.loads(phase9_9_metadata_path(tmp).read_text(encoding="utf-8"))
            self.assertEqual(metadata["candidate_id"], "logistic_c1")
            self.assertEqual(metadata["freeze_authority"], "ACCEPTANCE_PASS_HIGHEST_COMPOSITE")


class TestPhase22AJMigrationReport(unittest.TestCase):
    def test_verdict_freeze_authority_migrated(self):
        from tradingbot.ml.research.phase22aj.freeze_wiring_validation import run_investigation

        result = run_investigation()
        self.assertEqual(result["verdict"], "FREEZE_AUTHORITY_MIGRATED")


class TestPhase22AJDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22aj"
        for name in (
            "production_winner_trace.json",
            "freeze_wiring_report.json",
            "authority_migration_report.json",
            "bypass_audit.json",
            "freeze_manifest_schema.json",
            "phase22aj_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22aj run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
