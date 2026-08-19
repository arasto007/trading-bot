"""Phase 29A — edge improvement deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase29a"

DELIVERABLES = [
    "trade_quality_scores.json",
    "winner_vs_loser_analysis.json",
    "signal_quality_filter.json",
    "false_signal_analysis.json",
    "market_context_analysis.json",
    "filter_threshold_analysis.json",
    "causality_validation.json",
    "stress_validation.json",
    "performance_comparison.json",
    "production_recommendation.json",
    "phase29a_final_report.json",
]

VERDICTS = {"EDGE_IMPROVEMENT_VALIDATED", "EDGE_IMPROVEMENT_INCONCLUSIVE"}


class TestPhase29A(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase29a_final_report.json").is_file():
            from tradingbot.ml.research.phase29a.run_investigation import run_phase29a

            run_phase29a()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_trade_quality_scores(self) -> None:
        tq = json.loads((PHASE_DIR / "trade_quality_scores.json").read_text(encoding="utf-8"))
        self.assertEqual(tq.get("trade_count"), 575)
        self.assertTrue(all(0 <= t["quality_score"] <= 100 for t in tq["trades"]))

    def test_causality_passes(self) -> None:
        cv = json.loads((PHASE_DIR / "causality_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(cv.get("all_pass"))

    def test_winner_loser_analysis(self) -> None:
        wvl = json.loads((PHASE_DIR / "winner_vs_loser_analysis.json").read_text(encoding="utf-8"))
        self.assertGreater(wvl.get("winner_count", 0), 0)
        self.assertGreater(wvl.get("loser_count", 0), 0)

    def test_production_recommendation(self) -> None:
        rec = json.loads((PHASE_DIR / "production_recommendation.json").read_text(encoding="utf-8"))
        self.assertTrue(rec.get("research_only"))
        self.assertIn("threshold", rec)
        self.assertIn("algorithm", rec)

    def test_filter_threshold_analysis(self) -> None:
        ft = json.loads((PHASE_DIR / "filter_threshold_analysis.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(ft.get("cutoff_results") or []), 3)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase29a_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)


if __name__ == "__main__":
    unittest.main()
