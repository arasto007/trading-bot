"""Phase 23B — feature pipeline repair tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP
from tradingbot.ml.research.phase23b.repair_validation import (
    REQUIRED_FEATURES,
    build_adapter_validation,
    build_feature_mapping_patch,
    build_regression_report,
    build_runtime_feature_validation,
    determine_verdict,
)
from tradingbot.ml.research.regime_router.phase99_feature_validation import validate_runtime_feature_vector


class TestPhase23BRepair(unittest.TestCase):
    def test_feature_map_covers_feature_order(self):
        patch = build_feature_mapping_patch()
        self.assertTrue(patch["map_covers_feature_order"])
        self.assertEqual(patch["missing_from_map"], [])
        for feature in REQUIRED_FEATURES:
            self.assertIn(feature, PHASE99_FEATURE_MAP)

    def test_feature_order_identical(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        report = build_runtime_feature_validation(base_dir=base_dir)
        self.assertTrue(report["checks"]["feature_order_identical"])

    def test_ema_cross_state_delivered(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        report = build_runtime_feature_validation(base_dir=base_dir)
        self.assertTrue(report["checks"]["ema_cross_state_delivered"])

    def test_predict_proba_executed(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        report = build_runtime_feature_validation(base_dir=base_dir)
        self.assertTrue(report["checks"]["predict_proba_executed"])

    def test_no_silent_zero_injection_on_missing_features(self):
        ok, errors = validate_runtime_feature_vector({"candle_direction": 0.0}, ["candle_direction", "ema_cross_state"])
        self.assertFalse(ok)
        self.assertIn("missing:ema_cross_state", errors)

    def test_model_pass_proxy_gt_zero(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        report = build_runtime_feature_validation(base_dir=base_dir)
        self.assertTrue(report["checks"]["model_pass_proxy_gt_zero"])

    def test_runtime_integrity_pass(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        regression = build_regression_report(base_dir=base_dir)
        self.assertTrue(regression["runtime_loader_integrity"])
        self.assertTrue(regression["unchanged"]["freeze_artifacts"])

    def test_adapter_order_match(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        adapter = build_adapter_validation(base_dir=base_dir)
        self.assertTrue(adapter["order_match"])


class TestPhase23BFinalReport(unittest.TestCase):
    def test_verdict_feature_pipeline_repaired(self):
        path = ROOT / "tradingbot" / "ml" / "research" / "phase23b" / "phase23b_final_report.json"
        if not path.is_file():
            self.skipTest("run phase23b run_investigation.py first")
        final = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "FEATURE_PIPELINE_REPAIRED")

    def test_determine_verdict_passes(self):
        runtime = {"checks": {
            "feature_order_identical": True,
            "ema_cross_state_delivered": True,
            "predict_proba_executed": True,
            "feature_builder_primary": True,
            "model_pass_proxy_gt_zero": True,
        }}
        regression = {"runtime_loader_integrity": True, "unchanged": {"freeze_artifacts": True}}
        self.assertEqual(determine_verdict(runtime, regression), "FEATURE_PIPELINE_REPAIRED")


if __name__ == "__main__":
    unittest.main()
