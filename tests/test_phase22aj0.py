"""Phase 22AJ0 — winner authority resolution tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase22aj0.winner_authority import (
    PRODUCTION_RULE_ID,
    build_winner_authority_trace,
    select_production_winner,
)


class TestPhase22AJ0Forensics(unittest.TestCase):
    def test_winner_trace_documents_five_definitions(self):
        trace = build_winner_authority_trace()
        names = {d["name"] for d in trace["definitions"]}
        self.assertIn("select_best", names)
        self.assertIn("evaluate_acceptance", names)
        self.assertIn("freeze_bridge_prototype", names)
        self.assertGreaterEqual(len(trace["conflicts_detected"]), 2)

    def test_select_best_differs_from_production_winner(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import (
            normalize_ml_base_dir,
            phase9_8_robustness_report_path,
            phase9_8_window_results_path,
            phase9_9_model_comparison_path,
        )
        from tradingbot.ml.research.phase22z.overfitting_rule_validation import load_baseline_numeric
        from tradingbot.ml.research.robustness_optimizer.candidate_selector import select_best

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        comparison = json.loads(phase9_9_model_comparison_path(base_dir).read_text(encoding="utf-8"))
        ranked = comparison["ranked_candidates"]
        p98 = json.loads(phase9_8_robustness_report_path(base_dir).read_text(encoding="utf-8"))
        win = json.loads(phase9_8_window_results_path(base_dir).read_text(encoding="utf-8"))
        baseline = dict(comparison["baseline_phase9_8"])
        baseline["mean_auc_gap"] = load_baseline_numeric(p98, win)["mean_auc_gap"]

        production = select_production_winner(ranked, baseline)
        best = select_best(ranked)
        self.assertIsNotNone(production)
        self.assertIsNotNone(best)
        self.assertNotEqual(production["experiment_id"], best["experiment_id"])

    def test_exactly_one_production_winner(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22aj0.winner_authority import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        table = result["candidate_eligibility_table"]
        self.assertEqual(table["production_eligible_count"], 1)
        self.assertEqual(
            table["resolved_production_winner"],
            "xgb_baseline_phase96__stable_except_unstable__RANGE",
        )

    def test_recommended_option_is_c(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22aj0.winner_authority import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertEqual(result["authority_options"]["recommended_option"], "C")

    def test_verdict_single_authority_defined(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22aj0.winner_authority import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertEqual(result["verdict"], "SINGLE_AUTHORITY_DEFINED")
        self.assertTrue(result["authority_resolution"]["ambiguity_resolved"])

    def test_production_rule_id(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22aj0.winner_authority import run_investigation

        result = run_investigation(base_dir=normalize_ml_base_dir(load_legacy_config().get("BASE_DIR")))
        self.assertEqual(result["production_rule"]["rule_id"], PRODUCTION_RULE_ID)


class TestPhase22AJ0Deliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22aj0"
        for name in (
            "winner_authority.json",
            "candidate_eligibility_table.json",
            "authority_resolution.json",
            "production_rule.json",
            "phase22aj0_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22aj0 run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22aj0_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "SINGLE_AUTHORITY_DEFINED")
        self.assertFalse(final["production_modified"])


if __name__ == "__main__":
    unittest.main()
