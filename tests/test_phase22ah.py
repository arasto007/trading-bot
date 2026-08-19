"""Phase 22AH — numeric acceptance rule validation tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22AHForensics(unittest.TestCase):
    def test_metric_trace_documents_producers(self):
        from tradingbot.ml.research.phase22ah.numeric_acceptance_validation import build_metric_trace

        trace = build_metric_trace()
        self.assertEqual(trace["metric"], "mean_auc_gap")
        self.assertGreaterEqual(len(trace["producers"]), 3)
        self.assertTrue(trace["aggregation"]["abs_applied_before_mean"])

    def test_gap_metrics_recomputes_baseline_mean(self):
        from tradingbot.ml.research.phase22ah.numeric_acceptance_validation import _gap_metrics, _window_gaps

        gaps = _window_gaps(
            [
                {"train_val_auc_gap": 0.4519},
                {"train_val_auc_gap": 0.3728},
                {"train_val_auc_gap": 0.3338},
                {"train_val_auc_gap": 0.3231},
                {"train_val_auc_gap": 0.1725},
            ]
        )
        stats = _gap_metrics(gaps)
        self.assertAlmostEqual(stats["mean_auc_gap"], 0.3308, places=4)
        self.assertAlmostEqual(stats["max_auc_gap"], 0.4519, places=4)

    def test_mean_metric_accepts_one_candidate(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import (
            normalize_ml_base_dir,
            phase9_8_robustness_report_path,
            phase9_8_window_results_path,
            phase9_9_model_comparison_path,
        )
        from tradingbot.ml.research.phase22ah.numeric_acceptance_validation import run_forensics
        from tradingbot.ml.research.phase22z.overfitting_rule_validation import load_baseline_numeric

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        result = run_forensics(base_dir=base_dir)
        alt = result["alternative_metric_simulation"]
        self.assertEqual(alt["results"]["mean_auc_gap"]["accepted_count"], 1)
        self.assertIn(
            "xgb_baseline_phase96__stable_except_unstable__RANGE",
            alt["results"]["mean_auc_gap"]["accepted"],
        )

    def test_recommendation_is_replace_with_numeric_mean(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ah.numeric_acceptance_validation import run_forensics

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        result = run_forensics(base_dir=base_dir)
        self.assertEqual(result["recommendation"], "REPLACE_WITH_NUMERIC_MEAN")

    def test_verdict_safe_to_patch(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ah.numeric_acceptance_validation import run_forensics

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        result = run_forensics(base_dir=base_dir)
        self.assertEqual(result["verdict"], "SAFE_TO_PATCH")

    def test_compatibility_runtime_unaffected(self):
        from tradingbot.ml.research.phase22ah.numeric_acceptance_validation import build_compatibility_report

        report = build_compatibility_report()
        health = next(r for r in report["impact_matrix"] if r["component"] == "HealthGate")
        self.assertFalse(health["affected"])

    def test_dependency_scan_finds_acceptance_rule(self):
        from tradingbot.ml.research.phase22ah.numeric_acceptance_validation import dependency_scan

        scan = dependency_scan(ROOT)
        self.assertGreater(scan["hit_counts"]["overfitting_risk_decreased"], 0)
        self.assertGreater(scan["hit_counts"]["mean_auc_gap"], 0)
        impl = scan["critical_dependencies"]["acceptance_implementation"]
        self.assertTrue(any("report_generator.py" in h["file"] for h in impl))


class TestPhase22AHDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22ah"
        for name in (
            "metric_trace.json",
            "stability_analysis.json",
            "alternative_metric_simulation.json",
            "baseline_sensitivity.json",
            "dependency_scan.json",
            "compatibility_report.json",
            "phase22ah_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22ah run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22ah_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "SAFE_TO_PATCH")
        self.assertEqual(final["recommendation"], "REPLACE_WITH_NUMERIC_MEAN")
        self.assertFalse(final["production_modified"])


if __name__ == "__main__":
    unittest.main()
