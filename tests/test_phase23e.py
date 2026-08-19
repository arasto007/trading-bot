"""Phase 23E — RANGE filter recalibration tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VERDICT_OPTIONS = {
    "KEEP_CURRENT_FILTERS",
    "MODIFY_RSI_ONLY",
    "MODIFY_ADX_ONLY",
    "CREATE_RANGE_SPECIFIC_FILTER_PROFILE",
    "REMOVE_RSI",
    "REMOVE_ADX",
    "REMOVE_BOTH",
}


class TestPhase23EStudy(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase23e.range_filter_study import run_study

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        cls.result = run_study(base_dir=base_dir)

    def test_search_space_generated(self) -> None:
        space = self.result["search_space"]
        self.assertGreater(space["total_profiles"], 100)
        self.assertIn("both", space["modes"])

    def test_grid_search_ranked(self) -> None:
        grid = self.result["grid_search_results"]
        self.assertGreater(grid["records_total"], 0)
        self.assertGreater(len(grid["top_20"]), 0)
        top = grid["top_20"][0]
        self.assertIn("profit_factor", top)
        self.assertIn("false_blocks", top)

    def test_walkforward_structure(self) -> None:
        wf = self.result["walkforward_results"]
        self.assertGreater(len(wf["profiles"]), 0)
        self.assertIn("stable", wf["profiles"][0])

    def test_monte_carlo_structure(self) -> None:
        mc = self.result["monte_carlo_results"]
        self.assertGreater(len(mc["profiles"]), 0)

    def test_statistical_validation(self) -> None:
        stats = self.result["statistical_validation"]
        self.assertIn("bootstrap_pf_diff_ci_95", stats)
        self.assertIn("cohens_d_effect_size", stats)

    def test_regime_validation_buckets(self) -> None:
        reg = self.result["regime_validation"]
        self.assertIn("RANGE", reg["regimes"])

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result["verdict"], VERDICT_OPTIONS)

    def test_recommendation_not_implemented(self) -> None:
        self.assertIn("NOT IMPLEMENTED", self.result["production_recommendation"]["implementation_status"])

    def test_repair_plan_design_only(self) -> None:
        self.assertEqual(self.result["repair_plan"]["implementation_status"], "DESIGN ONLY")


class TestPhase23EDeliverables(unittest.TestCase):
    def test_files_exist(self) -> None:
        out = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase23e"
        required = (
            "grid_search_results.json",
            "walkforward_results.json",
            "monte_carlo_results.json",
            "statistical_validation.json",
            "regime_validation.json",
            "safety_analysis.json",
            "winner_profile.json",
            "production_recommendation.json",
            "repair_plan.json",
            "phase23e_final_report.json",
        )
        missing = [n for n in required if not (out / n).is_file()]
        if missing:
            import tradingbot.ml.research.phase23e.run_study as runner

            runner.main()
        for name in required:
            self.assertTrue((out / name).is_file(), msg=f"missing {name}")
            payload = json.loads((out / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "23E")


if __name__ == "__main__":
    unittest.main()
