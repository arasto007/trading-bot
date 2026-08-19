"""Phase 22AL — production candidate live validation tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
from tradingbot.ml.research.phase22al.live_validation import (
    EXPECTED_CANDIDATE_ID,
    EXPECTED_EXPERIMENT_ID,
    build_frozen_model_validation,
    build_probability_health_report,
    build_runtime_safety_report,
    determine_verdict,
)


class TestPhase22ALValidation(unittest.TestCase):
    def test_frozen_model_matches_production_winner(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir, phase9_9_model_path

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        if not phase9_9_model_path(base_dir).is_file():
            self.skipTest("phase9_9 artifacts missing; run phase22ak first")

        report = build_frozen_model_validation(base_dir=base_dir)
        self.assertTrue(report["candidate_matches"])
        self.assertTrue(report["experiment_matches"])
        self.assertEqual(report["candidate_id"], EXPECTED_CANDIDATE_ID)
        self.assertEqual(report["experiment_id"], EXPECTED_EXPERIMENT_ID)
        self.assertTrue(report["integrity_passed"])

    def test_runtime_loader_succeeds(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir, phase9_9_model_path

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        if not phase9_9_model_path(base_dir).is_file():
            self.skipTest("phase9_9 artifacts missing")

        bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
        prob = bundle.predict_proba({feature: 0.0 for feature in bundle.feature_order})
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 1.0)

    def test_probability_health_passes(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22al.live_validation import build_historical_replay_report

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        historical = build_historical_replay_report(base_dir=base_dir)
        health = build_probability_health_report(historical)
        self.assertTrue(health["probability_gate_passed"])
        self.assertTrue(health["no_single_side_degeneration"])
        self.assertTrue(health["no_collapse"])

    def test_runtime_safety_passes(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        safety = build_runtime_safety_report(base_dir=base_dir)
        self.assertTrue(safety["healthgate_phase9_passes"])
        self.assertTrue(safety["no_default_config_literal"])
        self.assertTrue(safety["load_build_if_missing_false"])

    def test_rejected_probability_profile_fails_verdict(self):
        verdict, _ = determine_verdict(
            frozen={"candidate_matches": True, "experiment_matches": True, "integrity_passed": True, "manifest_present": False},
            probability_health={"probability_gate_passed": False, "no_single_side_degeneration": False},
            runtime_safety={"healthgate_phase9_passes": True, "no_default_config_literal": True},
            historical_report={"datasets": {"full_dataset_v2": {"replay": {"signals": {"BUY": 1, "SELL": 1}}}}},
            pipeline_report={"generated_signals": 10},
        )
        self.assertEqual(verdict, "MODEL_NEEDS_RESEARCH")


class TestPhase22ALInvestigation(unittest.TestCase):
    def test_verdict_model_validated_for_live(self):
        final_path = ROOT / "tradingbot" / "ml" / "research" / "phase22al" / "phase22al_final_report.json"
        if not final_path.is_file():
            self.skipTest("run phase22al run_investigation.py first")
        final = json.loads(final_path.read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "MODEL_VALIDATED_FOR_LIVE")
        self.assertEqual(final.get("experiment_id"), EXPECTED_EXPERIMENT_ID)


class TestPhase22ALDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22al"
        for name in (
            "frozen_model_validation.json",
            "historical_replay_report.json",
            "signal_distribution.json",
            "trade_metrics.json",
            "probability_health_report.json",
            "logistic_vs_xgb_comparison.json",
            "runtime_safety_report.json",
            "phase22al_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22al run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
