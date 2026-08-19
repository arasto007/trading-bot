"""Phase 27E deliverable presence and signal accounting checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27e"

DELIVERABLES = [
    "signal_trace.json",
    "riskgate_rejection_statistics.json",
    "execution_statistics.json",
    "journal_flow_statistics.json",
    "signal_loss_funnel.json",
    "stage_statistics.json",
    "root_cause_rank.json",
    "final_report.json",
]

VERDICTS = {"BOTTLENECK_IDENTIFIED", "BOTTLENECK_NOT_FOUND"}


class TestPhase27EDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report.get("verdict"), "BOTTLENECK_IDENTIFIED")

    def test_all_762_signals_traced(self) -> None:
        trace = json.loads((PHASE_DIR / "signal_trace.json").read_text(encoding="utf-8"))
        self.assertEqual(trace.get("total_emitted_ml_signals"), 762)
        self.assertEqual(trace.get("unknown_losses"), 0)

    def test_riskgate_accounts_for_losses(self) -> None:
        risk = json.loads(
            (PHASE_DIR / "riskgate_rejection_statistics.json").read_text(encoding="utf-8")
        )
        self.assertEqual(risk.get("riskgate_blocked"), 760)
        self.assertEqual(risk.get("riskgate_passed"), 2)
        by_reason = risk.get("by_reason") or {}
        self.assertEqual(by_reason.get("max positions for symbol", 0), 753)
        self.assertEqual(by_reason.get("opposite direction position open", 0), 7)

    def test_funnel_execution_count(self) -> None:
        funnel = json.loads((PHASE_DIR / "signal_loss_funnel.json").read_text(encoding="utf-8"))
        self.assertEqual(funnel.get("emitted"), 762)
        completed = next(s for s in funnel["funnel"] if s["stage"] == "completed_trade")
        self.assertEqual(completed["count"], 2)


if __name__ == "__main__":
    unittest.main()
