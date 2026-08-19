"""Phase 23F — shadow validation tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VERDICT_OPTIONS = {
    "KEEP_PHASE22C",
    "DEPLOY_RANGE_PROFILE",
    "COLLECT_MORE_DATA",
    "REJECT_PHASE23E_PROFILE",
}


class TestPhase23FShadow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase23f.shadow_validation import run_shadow_validation

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        cls.result = run_shadow_validation(base_dir=base_dir, quick=True)

    def test_dual_pipelines_present(self) -> None:
        self.assertIn("pipeline_a_results", self.result)
        self.assertIn("pipeline_b_results", self.result)
        self.assertEqual(
            self.result["pipeline_a_results"]["profile"]["profile_id"],
            "production_phase22c",
        )

    def test_multiple_windows(self) -> None:
        windows = self.result["window_validation"]["windows"]
        for key in ("last_300_bars", "last_365_days"):
            self.assertIn(key, windows)

    def test_walkforward_both_pipelines(self) -> None:
        wf = self.result["walkforward_validation"]
        self.assertIn("pipeline_a", wf)
        self.assertIn("pipeline_b", wf)

    def test_monte_carlo_both_pipelines(self) -> None:
        mc = self.result["monte_carlo_validation"]
        self.assertIn("pipeline_a", mc)
        self.assertIn("pipeline_b", mc)

    def test_runtime_safety_read_only(self) -> None:
        safety = self.result["runtime_safety"]
        self.assertFalse(safety["production_modified"])
        self.assertFalse(safety["execution_enabled"])

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result["verdict"], VERDICT_OPTIONS)

    def test_not_deployed(self) -> None:
        self.assertIn("NOT DEPLOYED", self.result["deployment_recommendation"]["implementation_status"])

    def test_parallel_comparison_structure(self) -> None:
        pc = self.result["parallel_comparison"]
        self.assertIn("divergent_signals_sample", pc)


class TestPhase23FDeliverables(unittest.TestCase):
    def test_files_exist(self) -> None:
        out = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase23f"
        required = (
            "pipeline_a_results.json",
            "pipeline_b_results.json",
            "parallel_comparison.json",
            "window_validation.json",
            "walkforward_validation.json",
            "monte_carlo_validation.json",
            "bootstrap_validation.json",
            "regime_validation.json",
            "runtime_safety.json",
            "deployment_recommendation.json",
            "phase23f_final_report.json",
        )
        missing = [n for n in required if not (out / n).is_file()]
        if missing:
            import tradingbot.ml.research.phase23f.run_validation as runner

            runner.main()
        for name in required:
            self.assertTrue((out / name).is_file(), msg=f"missing {name}")
            payload = json.loads((out / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "23F")


if __name__ == "__main__":
    unittest.main()
