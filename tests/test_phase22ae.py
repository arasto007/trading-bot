"""Phase 22AE — freeze decision forensics tests."""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22AEForensics(unittest.TestCase):
    def test_default_config_is_module_literal(self):
        from tradingbot.ml.research.phase22ae.freeze_forensics import build_default_config_trace

        trace = build_default_config_trace()
        cls = trace["classification"]
        self.assertTrue(cls["hardcoded"])
        self.assertFalse(cls["loaded_from_json"])
        self.assertFalse(cls["loaded_from_environment"])
        self.assertEqual(trace["builder"], "None — module-level literal assigned at import")

    def test_freeze_uses_contract_not_hardcoded_logistic(self):
        src = (ROOT / "tradingbot/ml/paper_trading/model_registry.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        freeze_fn = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "freeze_phase9_9_from_contract"
        )
        body_src = ast.get_source_segment(src, freeze_fn) or ""
        self.assertNotIn('candidate_id="logistic_strong_reg"', body_src)
        self.assertIn("contract", body_src)

    def test_optimizer_calls_freeze_on_acceptance(self):
        opt_src = (ROOT / "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("freeze_phase9_9_artifacts", opt_src)
        self.assertIn("select_production_winner", opt_src)
        self.assertIn("build_freeze_contract", opt_src)

    def test_no_caller_passes_config_to_freeze(self):
        from tradingbot.ml.research.phase22ae.freeze_forensics import build_freeze_parameter_analysis

        params = build_freeze_parameter_analysis()
        self.assertEqual(params["repository_calls_with_config_kwarg"], 0)
        self.assertIn("candidate_id → 'logistic_strong_reg'", params["always_overridden_by_hardcode"][0])

    def test_optimizer_connection_broken(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ae.freeze_forensics import build_optimizer_connection

        conn = build_optimizer_connection(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertFalse(conn["optimizer_can_reach_freeze"])
        self.assertFalse(conn["freeze_reads_optimizer"]["reads_best_candidate_id"])

    def test_verdict_multiple_causes(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ae.freeze_forensics import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertEqual(result["verdict"], "MULTIPLE_CAUSES")
        applied = [c["id"] for c in result["root_causes"] if c["applies"]]
        self.assertIn("HARDCODED_CONFIG", applied)
        self.assertIn("DISCONNECTED_PIPELINE", applied)
        self.assertNotIn("DEFAULT_OVERRIDE", applied)


class TestPhase22AEDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22ae"
        for name in (
            "freeze_trace.json",
            "default_config_trace.json",
            "optimizer_connection.json",
            "hardcoded_constants.json",
            "repository_references.json",
            "phase22ae_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22ae run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22ae_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "MULTIPLE_CAUSES")
        self.assertFalse(final["production_modified"])


if __name__ == "__main__":
    unittest.main()
