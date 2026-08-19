"""Phase 27J — edge decomposition deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27j"

DELIVERABLES = [
    "edge_per_trade.json",
    "winner_analysis.json",
    "loser_analysis.json",
    "capture_efficiency.json",
    "exit_quality.json",
    "edge_sources.json",
    "r_multiple_analysis.json",
    "opportunity_loss.json",
    "edge_decay.json",
    "root_cause_rank.json",
    "final_report.json",
]

VERDICTS = {"EDGE_ROOT_CAUSE_IDENTIFIED", "EDGE_ROOT_CAUSE_NOT_IDENTIFIED"}
EXPECTED_TRADES = 575


class TestPhase27JDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "final_report.json").is_file():
            raise unittest.SkipTest("Phase 27J deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_trade_count(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report.get("completed_trades"), EXPECTED_TRADES)

    def test_edge_per_trade_fields(self) -> None:
        edge = json.loads((PHASE_DIR / "edge_per_trade.json").read_text(encoding="utf-8"))
        self.assertEqual(edge.get("trade_count"), EXPECTED_TRADES)
        trades = edge.get("trades") or []
        self.assertEqual(len(trades), EXPECTED_TRADES)
        sample = trades[0]
        for key in ("gross_edge", "spread_cost", "net_edge", "final_r", "capture_efficiency"):
            self.assertIn(key, sample)

    def test_winner_loser_split(self) -> None:
        winner = json.loads((PHASE_DIR / "winner_analysis.json").read_text(encoding="utf-8"))
        loser = json.loads((PHASE_DIR / "loser_analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(winner["winner_count"] + loser["loser_count"], EXPECTED_TRADES)

    def test_r_multiple_gap(self) -> None:
        rmult = json.loads((PHASE_DIR / "r_multiple_analysis.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(rmult.get("planned_vs_realized_gap"))
        self.assertGreater(rmult.get("planned_rr_mean", 0), rmult.get("average_final_r", 0))

    def test_root_cause_ranked(self) -> None:
        rc = json.loads((PHASE_DIR / "root_cause_rank.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(rc.get("ranked_causes") or []), 5)
        self.assertTrue(rc.get("primary_root_cause"))

    def test_edge_decay_components(self) -> None:
        decay = json.loads((PHASE_DIR / "edge_decay.json").read_text(encoding="utf-8"))
        lost = decay.get("edge_lost_pct_of_gross") or {}
        for key in ("spread", "slippage", "missed_move"):
            self.assertIn(key, lost)


if __name__ == "__main__":
    unittest.main()
