"""Phase 23D — execution filter validation tests (read-only)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VERDICT_OPTIONS = {
    "FILTER_CORRECT",
    "FILTER_TOO_STRICT",
    "FILTER_FOR_WRONG_REGIME",
    "FILTER_OUTDATED",
    "MULTIPLE_ROOT_CAUSES",
}


class TestPhase23DInvestigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase23d.filter_validation_research import run_investigation

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        cls.result = run_investigation(base_dir=base_dir)

    def test_filter_history_documents_origin(self) -> None:
        hist = self.result["filter_history"]
        self.assertTrue(hist["rsi_filter"]["introduced_by"].startswith("Phase 19C"))
        self.assertIn("19B", hist["rsi_filter"]["research_origin"])

    def test_ownership_maps_kernel_caller(self) -> None:
        owners = {f["name"]: f for f in self.result["filter_ownership"]["filters"]}
        self.assertIn("kernel_adapter", owners["rsi_filter"]["caller"])

    def test_no_phase99_range_only_validation(self) -> None:
        orig = self.result["original_validation"]
        self.assertFalse(orig["phase99_range_specific_evidence"]["found"])

    def test_empirical_range_cohort(self) -> None:
        emp = self.result["empirical_filter_analysis"]
        tail = emp["tail_300_bars"]
        self.assertGreaterEqual(tail["pipeline_actionable_range_signals"], 0)
        self.assertIn("filter_pass", tail)
        self.assertIn("filter_blocked", tail)

    def test_counterfactual_has_on_off(self) -> None:
        cf = self.result["counterfactual_analysis"]["tail_300_bars"]
        self.assertIn("filter_on", cf)
        self.assertIn("filter_off", cf)

    def test_false_block_metrics(self) -> None:
        fb = self.result["false_block_analysis"]["tail_300_bars"]
        for key in ("precision", "recall_vs_all_losers", "false_blocks_winner_would_have_traded"):
            self.assertIn(key, fb)

    def test_regime_analysis_range_only(self) -> None:
        reg = self.result["regime_analysis"]
        self.assertEqual(reg["cohort_regime"][:5], "RANGE")

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result["verdict"], VERDICT_OPTIONS)

    def test_repair_design_not_implemented(self) -> None:
        self.assertIn("NOT IMPLEMENTED", self.result["repair_design"]["implementation_status"])


class TestPhase23DDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        out = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase23d"
        required = (
            "filter_history.json",
            "filter_ownership.json",
            "original_validation.json",
            "empirical_filter_analysis.json",
            "counterfactual_analysis.json",
            "false_block_analysis.json",
            "regime_analysis.json",
            "dependency_analysis.json",
            "root_cause_report.json",
            "repair_design.json",
            "phase23d_final_report.json",
        )
        missing = [n for n in required if not (out / n).is_file()]
        if missing:
            import tradingbot.ml.research.phase23d.run_investigation as runner

            runner.main()
        for name in required:
            self.assertTrue((out / name).is_file(), msg=f"missing {name}")
            payload = json.loads((out / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "23D")


if __name__ == "__main__":
    unittest.main()
