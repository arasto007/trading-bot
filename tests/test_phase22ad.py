"""Phase 22AD — runtime authority trace tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22ADTrace(unittest.TestCase):
    def test_live_runner_wires_ml_kernel_registry(self):
        src = (ROOT / "tradingbot/application/live_runner.py").read_text(encoding="utf-8")
        self.assertIn("build_strategy_registry", src)
        self.assertNotIn("shadow_engine", src)
        self.assertNotIn("freeze_phase9_9_artifacts", src)

    def test_kernel_adapter_uses_registry_inner_not_shadow(self):
        src = (ROOT / "tradingbot/ml/integration/kernel_adapter.py").read_text(encoding="utf-8")
        self.assertIn("_engine_inners", src)
        self.assertIn("build_market_context", src)
        self.assertNotIn("ShadowEngine", src)
        self.assertNotIn("build_if_missing=True", src)

    def test_range_adapter_loads_with_build_if_missing_false(self):
        src = (ROOT / "tradingbot/ml/research/regime_router/range_engine_adapter.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("load_phase9_9_bundle(base_dir=None, build_if_missing=False)", src)

    def test_runtime_authority_is_registry(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ad.runtime_trace import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertEqual(result["verdict"], "REGISTRY_IS_RUNTIME_AUTHORITY")
        self.assertEqual(result["runtime_authority"]["single_runtime_authority"], "Registry")
        self.assertFalse(result["artifact_overwrite_trace"]["live_process_can_overwrite_phase9_9_artifacts_after_startup"])

    def test_live_path_excludes_shadow_components(self):
        from tradingbot.ml.research.phase22ad.runtime_trace import _verify_live_path_excludes_shadow

        checks = _verify_live_path_excludes_shadow()
        self.assertFalse(checks["shadow_engine_imported"])
        self.assertFalse(checks["kernel_shadow_runner_imported"])
        self.assertFalse(checks["freeze_in_live_chain"])
        self.assertFalse(checks["build_if_missing_true_in_live_chain"])

    def test_bundle_trace_origin_is_model_pkl(self):
        from tradingbot.ml.research.phase22ad.runtime_trace import build_runtime_bundle_trace

        trace = build_runtime_bundle_trace(base_dir=None)
        self.assertEqual(trace["runtime_model_origin"], "model.pkl (frozen disk artifact)")
        excluded = {x["source"] for x in trace["excluded_sources"]}
        self.assertIn("Phase 9.9 Optimizer", excluded)
        self.assertIn("ShadowEngine / KernelShadowRunner / MLAdapter", excluded)


class TestPhase22ADDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22ad"
        for name in (
            "runtime_sequence.json",
            "runtime_call_chain.json",
            "runtime_authority.json",
            "runtime_bundle_trace.json",
            "artifact_overwrite_trace.json",
            "phase22ad_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22ad run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22ad_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "REGISTRY_IS_RUNTIME_AUTHORITY")
        self.assertFalse(final["production_modified"])


if __name__ == "__main__":
    unittest.main()
