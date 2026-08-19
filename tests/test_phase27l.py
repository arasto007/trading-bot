"""Phase 27L — exit engine investigation deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27l"

DELIVERABLES = [
    "exit_timeline.json",
    "profit_timeline.json",
    "reversal_analysis.json",
    "exit_simulations.json",
    "edge_recovery.json",
    "loser_recovery.json",
    "winner_preservation.json",
    "exit_scoreboard.json",
    "exit_ranking.json",
    "final_report.json",
]

VERDICTS = {"EXIT_ENGINE_ROOT_CAUSE_IDENTIFIED", "EXIT_ENGINE_ROOT_CAUSE_NOT_IDENTIFIED"}
EXPECTED_TRADES = 575


class TestPhase27LDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "final_report.json").is_file():
            raise unittest.SkipTest("Phase 27L deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_trade_count(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report.get("completed_trades"), EXPECTED_TRADES)

    def test_exit_simulations_strategies(self) -> None:
        sim = json.loads((PHASE_DIR / "exit_simulations.json").read_text(encoding="utf-8"))
        strategies = sim.get("strategies") or {}
        self.assertIn("current_tp_sl", strategies)
        self.assertIn("breakeven_0.5r", strategies)
        self.assertGreaterEqual(len(strategies), 8)

    def test_exit_ranking(self) -> None:
        rank = json.loads((PHASE_DIR / "exit_ranking.json").read_text(encoding="utf-8"))
        self.assertTrue(rank.get("best_strategy"))
        self.assertGreaterEqual(len(rank.get("ranked") or []), 5)

    def test_recommended_beats_baseline_net(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        best_net = (report.get("recommended_metrics") or {}).get("net_profit", 0)
        base_net = (report.get("baseline_metrics") or {}).get("net_profit", 0)
        self.assertGreater(best_net, base_net)

    def test_exit_timeline_bars(self) -> None:
        timeline = json.loads((PHASE_DIR / "exit_timeline.json").read_text(encoding="utf-8"))
        traces = timeline.get("traces") or []
        self.assertEqual(len(traces), EXPECTED_TRADES)
        self.assertIn("bars", traces[0])
        self.assertIn("current_r", traces[0]["bars"][0])

    def test_loser_recovery_present(self) -> None:
        lr = json.loads((PHASE_DIR / "loser_recovery.json").read_text(encoding="utf-8"))
        self.assertEqual(lr.get("baseline_loser_count"), 353)
        self.assertTrue(lr.get("by_strategy"))


if __name__ == "__main__":
    unittest.main()
