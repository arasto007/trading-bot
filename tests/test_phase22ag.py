"""Phase 22AG — acceptance gate calibration forensics tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22AGForensics(unittest.TestCase):
    def test_acceptance_flow_documents_five_checks(self):
        from tradingbot.ml.research.phase22ag.acceptance_forensics import build_acceptance_flow

        flow = build_acceptance_flow()
        names = [c["name"] for c in flow["checks"]]
        self.assertEqual(len(names), 5)
        self.assertIn("overfitting_risk_decreased", names)
        self.assertIn("probability_quality_passed", names)

    def test_current_variant_accepts_one_after_patch(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ag.acceptance_forensics import run_forensics

        result = run_forensics(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertEqual(result["candidate_simulation"]["variants"]["A"]["accepted_count"], 1)

    def test_variant_d_accepts_at_least_one(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ag.acceptance_forensics import run_forensics

        result = run_forensics(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        d = result["candidate_simulation"]["variants"]["D"]
        self.assertGreaterEqual(d["accepted_count"], 1)

    def test_root_cause_multiple(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ag.acceptance_forensics import run_forensics

        result = run_forensics(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertEqual(result["root_cause"], "MULTIPLE_CAUSES")

    def test_minimal_change_targets_report_generator(self):
        from tradingbot.ml.research.phase22ag.acceptance_forensics import build_minimal_change_design, run_candidate_simulation
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import (
            normalize_ml_base_dir,
            phase9_8_robustness_report_path,
            phase9_8_window_results_path,
            phase9_9_model_comparison_path,
        )
        from tradingbot.ml.research.phase22z.overfitting_rule_validation import load_baseline_numeric

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        comparison = json.loads(phase9_9_model_comparison_path(base_dir).read_text(encoding="utf-8"))
        ranked = comparison["ranked_candidates"]
        baseline = comparison["baseline_phase9_8"]
        baseline_numeric = load_baseline_numeric(
            json.loads(phase9_8_robustness_report_path(base_dir).read_text(encoding="utf-8")),
            json.loads(phase9_8_window_results_path(base_dir).read_text(encoding="utf-8")),
        )
        sim = run_candidate_simulation(ranked, baseline, baseline_numeric)
        design = build_minimal_change_design(sim)
        self.assertIn("report_generator.py", design["file"])
        self.assertEqual(design["function"], "evaluate_acceptance")

    def test_verdict_ready_for_phase_2(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ag.acceptance_forensics import determine_verdict, run_forensics

        result = run_forensics(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertEqual(determine_verdict(result["candidate_simulation"]), "READY_FOR_PHASE_2_IMPLEMENTATION")
        self.assertEqual(result["verdict"], "READY_FOR_PHASE_2_IMPLEMENTATION")


class TestPhase22AGDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22ag"
        for name in (
            "acceptance_flow.json",
            "rule_analysis.json",
            "overfitting_rule_analysis.json",
            "candidate_simulation.json",
            "acceptance_contract.json",
            "minimal_change_design.json",
            "phase22ag_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22ag run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22ag_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "READY_FOR_PHASE_2_IMPLEMENTATION")
        self.assertFalse(final["production_modified"])


if __name__ == "__main__":
    unittest.main()
