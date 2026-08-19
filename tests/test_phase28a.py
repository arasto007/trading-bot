"""Phase 28A — A/B paper trading deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase28a"

DELIVERABLES = [
    "strategy_a_results.json",
    "strategy_b_results.json",
    "paired_trade_comparison.json",
    "head_to_head.json",
    "equity_comparison.json",
    "risk_comparison.json",
    "montecarlo_comparison.json",
    "decision_matrix.json",
    "phase28a_final_report.json",
]

VERDICTS = {"HYBRID_B_IS_BEST", "TIME_EXIT_IS_BEST", "NO_STATISTICAL_DIFFERENCE"}


class TestPhase28ADeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase28a_final_report.json").is_file():
            raise unittest.SkipTest("Phase 28A deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase28a_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_strategy_results_windows(self) -> None:
        a = json.loads((PHASE_DIR / "strategy_a_results.json").read_text(encoding="utf-8"))
        b = json.loads((PHASE_DIR / "strategy_b_results.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(a.get("windows") or {}), 3)
        self.assertGreater(a["aggregate"]["completed_trades"], 0)
        self.assertEqual(b["aggregate"]["completed_trades"], a["aggregate"]["completed_trades"])

    def test_paired_comparison(self) -> None:
        paired = json.loads((PHASE_DIR / "paired_trade_comparison.json").read_text(encoding="utf-8"))
        self.assertGreater(paired.get("paired_trade_count", 0), 0)
        total = paired["hybrid_wins"] + paired["time_exit_wins"] + paired["draws"]
        self.assertEqual(total, paired["paired_trade_count"])

    def test_head_to_head(self) -> None:
        h2h = json.loads((PHASE_DIR / "head_to_head.json").read_text(encoding="utf-8"))
        self.assertEqual(h2h.get("trade_count"), len(h2h.get("trades") or []))

    def test_montecarlo_1000(self) -> None:
        mc = json.loads((PHASE_DIR / "montecarlo_comparison.json").read_text(encoding="utf-8"))
        seq = (mc.get("strategies") or {}).get("hybrid_b", {}).get("sequence_shuffle", {})
        self.assertEqual(seq.get("simulations"), 1000)

    def test_decision_matrix(self) -> None:
        dm = json.loads((PHASE_DIR / "decision_matrix.json").read_text(encoding="utf-8"))
        self.assertIn("strategy_a", dm)
        self.assertIn("strategy_b", dm)
        self.assertIn(dm.get("decision_winner"), ("hybrid_b", "time_exit", "tie"))


if __name__ == "__main__":
    unittest.main()
