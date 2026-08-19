"""Phase 22AC — freeze integration radius investigation tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22ACForensics(unittest.TestCase):
    def test_multiple_authorities_not_single_registry(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ac.registry_investigation import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        auth = result["authority_analysis"]
        self.assertFalse(auth["single_authority"])
        self.assertEqual(auth["primary_write_authority"], "freeze_phase9_9_artifacts (DEFAULT_CONFIG)")

    def test_single_freeze_writer_for_phase9_9(self):
        from tradingbot.ml.research.phase22ac.registry_investigation import build_artifact_write_paths

        paths = build_artifact_write_paths()
        self.assertTrue(paths["single_writer_function"])
        self.assertEqual(paths["phase9_9_production_write_function"], "freeze_phase9_9_artifacts")
        artifacts = {p["artifact"] for p in paths["write_paths"]}
        self.assertEqual(
            artifacts,
            {"model.pkl", "scaler.pkl", "feature_order.json", "config.json", "metadata.json"},
        )

    def test_hidden_couplings_include_critical_items(self):
        from tradingbot.ml.research.phase22ac.registry_investigation import build_hidden_couplings

        couplings = build_hidden_couplings()
        ids = {c["id"] for c in couplings["couplings"]}
        self.assertIn("default_config_vs_optimizer", ids)
        self.assertIn("shadow_rebuilds_artifacts", ids)
        self.assertGreaterEqual(couplings["count_by_risk"]["CRITICAL"], 2)

    def test_repository_scan_finds_core_symbols(self):
        from tradingbot.ml.research.phase22ac.registry_investigation import scan_repository_usage

        usage = scan_repository_usage()
        self.assertGreater(len(usage["load_phase9_9_bundle"]), 10)
        self.assertGreater(len(usage["DEFAULT_CONFIG"]), 0)
        self.assertGreater(len(usage["freeze_phase9_9_artifacts"]), 5)

    def test_verdict_is_multiple_authorities(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ac.registry_investigation import determine_verdict, run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        verdict = determine_verdict(result["authority_analysis"], result["hidden_couplings"])
        self.assertEqual(verdict, "MULTIPLE_AUTHORITIES_EXIST")
        self.assertEqual(result["verdict"], "MULTIPLE_AUTHORITIES_EXIST")


class TestPhase22ACDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22ac"
        for name in (
            "model_registry_architecture.json",
            "bundle_dependency_graph.json",
            "artifact_write_paths.json",
            "authority_analysis.json",
            "hidden_couplings.json",
            "impact_radius.json",
            "phase22ac_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22ac run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22ac_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "MULTIPLE_AUTHORITIES_EXIST")
        self.assertFalse(final["production_modified"])


if __name__ == "__main__":
    unittest.main()
