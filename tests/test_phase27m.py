"""Phase 27M — exit robustness deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27m"

DELIVERABLES = [
    "window_30.json",
    "window_60.json",
    "window_90.json",
    "window_180.json",
    "window_365.json",
    "stability_analysis.json",
    "montecarlo_analysis.json",
    "walkforward_analysis.json",
    "overfitting_report.json",
    "global_ranking.json",
    "phase27m_final_report.json",
]

VERDICTS = {"EXIT_STRATEGY_ROBUST", "EXIT_STRATEGY_OVERFIT", "EXIT_STRATEGY_INCONCLUSIVE"}
STRATEGIES = {
    "current_tp_sl",
    "time_exit",
    "dynamic_tp_1.5r",
    "structure_exit",
    "atr_exit",
    "partial_close_50",
}


class TestPhase27MDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase27m_final_report.json").is_file():
            raise unittest.SkipTest("Phase 27M deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase27m_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_window_30_strategies(self) -> None:
        w = json.loads((PHASE_DIR / "window_30.json").read_text(encoding="utf-8"))
        strategies = set((w.get("strategies") or {}).keys())
        self.assertTrue(STRATEGIES.issubset(strategies))

    def test_stability_scores(self) -> None:
        stab = json.loads((PHASE_DIR / "stability_analysis.json").read_text(encoding="utf-8"))
        self.assertIn("by_strategy", stab)
        self.assertIn("time_exit", stab["by_strategy"])

    def test_global_ranking(self) -> None:
        gr = json.loads((PHASE_DIR / "global_ranking.json").read_text(encoding="utf-8"))
        self.assertTrue(gr.get("global_winner"))
        self.assertGreaterEqual(len(gr.get("ranked") or []), 6)

    def test_montecarlo_simulations(self) -> None:
        mc = json.loads((PHASE_DIR / "montecarlo_analysis.json").read_text(encoding="utf-8"))
        seq = (mc.get("strategies") or {}).get("time_exit", {}).get("sequence_shuffle", {})
        self.assertEqual(seq.get("simulations"), 1000)

    def test_walkforward_winners(self) -> None:
        wf = json.loads((PHASE_DIR / "walkforward_analysis.json").read_text(encoding="utf-8"))
        self.assertIn("window_winners", wf)
        self.assertGreaterEqual(len(wf.get("window_winners") or {}), 3)


if __name__ == "__main__":
    unittest.main()
