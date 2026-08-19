"""Phase 31C — realistic exit edge recovery tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase31c"

DELIVERABLES = [
    *[f"exit_candidate_{i:02d}.json" for i in range(1, 13)],
    "counterfactual_results.json",
    "walkforward_validation.json",
    "bootstrap_validation.json",
    "montecarlo_validation.json",
    "capture_efficiency_analysis.json",
    "production_ranking.json",
    "implementation_priority.json",
    "phase31c_final_report.json",
]

VERDICTS = {"REALISTIC_EXIT_FOUND", "NO_REALISTIC_IMPROVEMENT"}

METRIC_KEYS = (
    "profit_factor",
    "expectancy",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown_pct",
    "trade_count",
    "net_profit",
    "recovery_factor",
    "win_rate_pct",
)


class TestPhase31C(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase31c_final_report.json").is_file():
            from tradingbot.ml.research.phase31c.run_investigation import run_phase31c

            run_phase31c()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31c_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(doc["verdict"], VERDICTS)
        self.assertFalse(doc.get("production_modified", True))
        self.assertTrue(doc.get("perfect_capture_forbidden"))

    def test_at_least_12_candidates(self) -> None:
        doc = json.loads((PHASE_DIR / "counterfactual_results.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(doc["candidates"]), 12)

    def test_baseline_pf_matches_31b(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31c_final_report.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(doc["production_baseline_pf"], 1.211, delta=0.05)

    def test_exit_candidate_metrics_complete(self) -> None:
        doc = json.loads((PHASE_DIR / "exit_candidate_01.json").read_text(encoding="utf-8"))
        for key in METRIC_KEYS:
            self.assertIn(key, doc["metrics"], msg=key)

    def test_no_future_info_flag(self) -> None:
        for i in range(1, 13):
            doc = json.loads((PHASE_DIR / f"exit_candidate_{i:02d}.json").read_text(encoding="utf-8"))
            self.assertFalse(doc.get("uses_future_info", False))

    def test_walkforward_validation_structure(self) -> None:
        doc = json.loads((PHASE_DIR / "walkforward_validation.json").read_text(encoding="utf-8"))
        self.assertIn("results", doc)
        self.assertIn("baseline_current", doc["results"])
        wf = doc["results"]["baseline_current"]
        self.assertIn("train_pf", wf)
        self.assertIn("test_pf", wf)
        self.assertIn("walkforward_pass", wf)

    def test_bootstrap_validation_structure(self) -> None:
        doc = json.loads((PHASE_DIR / "bootstrap_validation.json").read_text(encoding="utf-8"))
        boot = doc["results"]["baseline_current"]
        self.assertIn("pf_median", boot)
        self.assertIn("pf_p05", boot)
        self.assertIn("pf_p95", boot)

    def test_montecarlo_validation_structure(self) -> None:
        doc = json.loads((PHASE_DIR / "montecarlo_validation.json").read_text(encoding="utf-8"))
        mc = doc["results"]["baseline_current"]
        self.assertIn("net_median", mc)
        self.assertIn("sequence_risk", mc)

    def test_production_ranking_conservative(self) -> None:
        doc = json.loads((PHASE_DIR / "production_ranking.json").read_text(encoding="utf-8"))
        self.assertGreater(len(doc["ranked"]), 0)
        top = doc["ranked"][0]
        self.assertNotEqual(top["name"], "baseline_current")
        self.assertIn("ranking_score", top)
        self.assertIn("robustness_score", top)

    def test_implementation_priority_forbids_perfect_capture(self) -> None:
        doc = json.loads((PHASE_DIR / "implementation_priority.json").read_text(encoding="utf-8"))
        self.assertIn("perfect_capture", doc["forbidden"])
        self.assertIn("recommended_exit", doc)

    def test_capture_efficiency_analysis(self) -> None:
        doc = json.loads((PHASE_DIR / "capture_efficiency_analysis.json").read_text(encoding="utf-8"))
        self.assertIn("by_candidate", doc)
        self.assertGreater(len(doc["by_candidate"]), 12)

    def test_exit_distribution_present(self) -> None:
        doc = json.loads((PHASE_DIR / "exit_candidate_08.json").read_text(encoding="utf-8"))
        self.assertIn("exit_distribution", doc)
        self.assertIsInstance(doc["exit_distribution"], dict)

    def test_recommended_not_highest_pf_only(self) -> None:
        final = json.loads((PHASE_DIR / "phase31c_final_report.json").read_text(encoding="utf-8"))
        ranking = json.loads((PHASE_DIR / "production_ranking.json").read_text(encoding="utf-8"))
        best_math_pf = final["best_mathematical_pf"]
        rec = final.get("best_realworld_exit")
        if rec:
            rec_pf = next(r["pf"] for r in ranking["ranked"] if r["name"] == rec)
            self.assertLessEqual(rec_pf, best_math_pf + 0.01)

    def test_trade_count_preserved(self) -> None:
        doc = json.loads((PHASE_DIR / "counterfactual_results.json").read_text(encoding="utf-8"))
        counts = {c["name"]: c["metrics"]["trade_count"] for c in doc["candidates"]}
        baseline_count = counts["baseline_current"]
        for name, count in counts.items():
            self.assertEqual(count, baseline_count, msg=name)


if __name__ == "__main__":
    unittest.main()
