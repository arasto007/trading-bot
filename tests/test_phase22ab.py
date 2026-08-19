"""Phase 22AB — freeze path authority forensics tests."""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22ABForensics(unittest.TestCase):
    def test_optimizer_wires_freeze_contract(self):
        src = (ROOT / "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("freeze_phase9_9_artifacts", src)
        self.assertIn("evaluate_acceptance", src)

    def test_freeze_requires_contract(self):
        src = (ROOT / "tradingbot/ml/paper_trading/model_registry.py").read_text(encoding="utf-8")
        self.assertNotIn("evaluate_acceptance", src)
        self.assertNotIn("DEFAULT_CONFIG:", src)
        self.assertNotIn("DEFAULT_CONFIG =", src)
        self.assertIn("validate_freeze_contract", src)

    def test_classification_proves_bypass_and_multiple_paths(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ab.freeze_forensics import run_forensics

        result = run_forensics(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        opts = result["freeze_authority_classification"]["options"]
        self.assertTrue(opts["C_freeze_ignores_acceptance_entirely"])
        self.assertTrue(opts["D_multiple_freeze_paths_exist"])
        self.assertFalse(opts["A_acceptance_must_pass_before_freeze"])

    def test_acceptance_guard_missing(self):
        from tradingbot.ml.research.phase22ab.freeze_forensics import build_freeze_guard_analysis

        guards = {g["guard"]: g["status"] for g in build_freeze_guard_analysis()["guards"]}
        self.assertEqual(guards["acceptance_guard"], "MISSING")


class TestPhase22ABDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22ab"
        for name in (
            "freeze_call_graph.json",
            "acceptance_vs_freeze_flow.json",
            "historical_freeze_evidence.json",
            "freeze_guard_analysis.json",
            "freeze_authority_classification.json",
            "impact_radius.json",
            "root_cause_report.json",
            "phase22ab_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22ab run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22ab_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "MULTIPLE_FREEZE_PATHS")


if __name__ == "__main__":
    unittest.main()
