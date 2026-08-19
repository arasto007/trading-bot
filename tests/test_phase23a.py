"""Phase 23A — read-only pipeline trace tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase23a.pipeline_trace import (
    FINAL_VERDICT,
    build_counter_trace,
    build_feature_flow,
    build_hold_chain_report,
    build_root_cause_report,
    build_runtime_vs_research,
    determine_verdict,
)


class TestPhase23ATrace(unittest.TestCase):
    def test_feature_flow_documents_ema_cross_state_gap(self):
        flow = build_feature_flow()
        issues = {row["feature"] for row in flow["mismatches"]}
        self.assertIn("ema_cross_state", issues)

    def test_hold_chain_model_pass_zero(self):
        report = build_hold_chain_report()
        if report.get("bars_evaluated") is None:
            self.skipTest("phase22al pipeline report missing")
        self.assertEqual(report["model_pass"], 0)
        self.assertGreater(report["stages"].get("decision_hold", 0), 0)

    def test_runtime_vs_research_feature_source_differs(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        comparison = build_runtime_vs_research(base_dir=base_dir)
        feature_dim = next(row for row in comparison["dimensions"] if row["dimension"] == "feature_source")
        self.assertFalse(feature_dim["match"])

    def test_root_cause_primary_is_feature_mapping(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        report = build_root_cause_report(base_dir=base_dir)
        self.assertTrue(report["classifications"]["FEATURE_MAPPING"])
        self.assertEqual(report["primary_root_cause"], "FEATURE_MAPPING")

    def test_verdict_feature_mapping_broken(self):
        report = build_root_cause_report()
        self.assertEqual(determine_verdict(report), FINAL_VERDICT)
        self.assertEqual(FINAL_VERDICT, "FEATURE_MAPPING_BROKEN")


class TestPhase23AInvestigation(unittest.TestCase):
    def test_final_report_verdict(self):
        path = ROOT / "tradingbot" / "ml" / "research" / "phase23a" / "phase23a_final_report.json"
        if not path.is_file():
            self.skipTest("run phase23a run_investigation.py first")
        final = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "FEATURE_MAPPING_BROKEN")
        self.assertEqual(final.get("model_pass"), 0)


class TestPhase23ADeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase23a"
        for name in (
            "runtime_call_graph.json",
            "feature_flow.json",
            "feature_validation.json",
            "predict_proba_trace.json",
            "signal_pipeline.json",
            "hold_chain.json",
            "filter_inventory.json",
            "counter_trace.json",
            "runtime_vs_research.json",
            "early_exit_analysis.json",
            "root_cause_report.json",
            "impact_radius.json",
            "repair_plan.json",
            "phase23a_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase23a run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
