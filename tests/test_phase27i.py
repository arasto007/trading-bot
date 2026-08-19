"""Phase 27I — slippage root cause investigation deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27i"

DELIVERABLES = [
    "slippage_breakdown.json",
    "direction_slippage.json",
    "regime_slippage.json",
    "duration_slippage.json",
    "rr_decay.json",
    "atr_analysis.json",
    "spread_analysis.json",
    "execution_price_analysis.json",
    "edge_decay.json",
    "root_cause_rank.json",
    "final_report.json",
]

VERDICTS = {"SLIPPAGE_ROOT_CAUSE_IDENTIFIED", "SLIPPAGE_ROOT_CAUSE_NOT_IDENTIFIED"}
EXPECTED_TRADES = 575


class TestPhase27IDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "final_report.json").is_file():
            raise unittest.SkipTest("Phase 27I deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_trade_count(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report.get("completed_trades"), EXPECTED_TRADES)

    def test_slippage_destroys_profit(self) -> None:
        bd = json.loads((PHASE_DIR / "slippage_breakdown.json").read_text(encoding="utf-8"))
        self.assertGreater(bd.get("total_slippage_loss", 0), bd.get("baseline_net_profit", 0) * 0.5)
        self.assertLess(bd.get("net_profit_after_slippage", 0), 0)

    def test_root_cause_ranked(self) -> None:
        rc = json.loads((PHASE_DIR / "root_cause_rank.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(rc.get("ranked_causes") or []), 5)
        self.assertTrue(rc.get("primary_root_cause"))

    def test_edge_decay_breakeven(self) -> None:
        edge = json.loads((PHASE_DIR / "edge_decay.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(edge.get("minimum_atr_mult_pf_below_1"))
        self.assertLess(float(edge["minimum_atr_mult_pf_below_1"]), 0.25)

    def test_execution_entry_exit_split(self) -> None:
        ex = json.loads((PHASE_DIR / "execution_price_analysis.json").read_text(encoding="utf-8"))
        self.assertIn(ex.get("primary_sensitivity"), ("entry", "exit", "both_equally"))
        total = ex.get("entry_contribution_pct", 0) + ex.get("exit_contribution_pct", 0)
        self.assertAlmostEqual(total, 100.0, delta=1.0)

    def test_direction_both_sides_analyzed(self) -> None:
        direction = json.loads((PHASE_DIR / "direction_slippage.json").read_text(encoding="utf-8"))
        self.assertGreater(direction.get("SELL", {}).get("trade_count", 0), 0)
        self.assertGreater(direction.get("BUY", {}).get("trade_count", 0), 0)


if __name__ == "__main__":
    unittest.main()
