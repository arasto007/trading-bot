"""Phase 28E — audit deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase28e"
PHASE28D_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase28d"

DELIVERABLES = [
    "drawdown_audit.json",
    "equity_audit.json",
    "balance_audit.json",
    "risk_audit.json",
    "margin_audit.json",
    "position_size_audit.json",
    "pnl_scaling_audit.json",
    "consistency_audit.json",
    "performance_recalculation.json",
    "phase28e_final_report.json",
]


class TestPhase28EAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE28D_DIR / "phase28d_final_report.json").is_file():
            raise unittest.SkipTest("Phase 28D deliverables required for Phase 28E audit")
        if not (PHASE_DIR / "phase28e_final_report.json").is_file():
            from tradingbot.ml.research.phase28e.run_investigation import run_phase28e

            run_phase28e()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_drawdown_reconciles(self) -> None:
        dd = json.loads((PHASE_DIR / "drawdown_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(dd.get("reported_matches_recalculation"))
        self.assertEqual(dd.get("is_87_97_pct_mathematically_correct"), True)

    def test_equity_and_balance_correct(self) -> None:
        eq = json.loads((PHASE_DIR / "equity_audit.json").read_text(encoding="utf-8"))
        bal = json.loads((PHASE_DIR / "balance_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(eq.get("equity_calculation_correct"))
        self.assertTrue(bal.get("balance_calculation_correct"))

    def test_fixed_lot_detected(self) -> None:
        pos = json.loads((PHASE_DIR / "position_size_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(pos.get("sizing_mode"), "fixed_broker_minimum")
        self.assertFalse(pos.get("realistic_for_200_account"))

    def test_risk_not_0_30_pct(self) -> None:
        risk = json.loads((PHASE_DIR / "risk_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(risk.get("actual_risk_exceeds_reported_target"))
        self.assertGreater(risk.get("true_average_risk_pct", 0), 1.0)

    def test_performance_recalc_matches(self) -> None:
        perf = json.loads((PHASE_DIR / "performance_recalculation.json").read_text(encoding="utf-8"))
        self.assertTrue(perf.get("metrics_match"))

    def test_final_answers(self) -> None:
        report = json.loads((PHASE_DIR / "phase28e_final_report.json").read_text(encoding="utf-8"))
        answers = report.get("answers") or {}
        self.assertEqual(answers.get("is_87_97_drawdown_mathematically_correct"), "YES")
        self.assertEqual(answers.get("is_risk_really_0_30_pct"), "NO")
        self.assertEqual(answers.get("is_lot_sizing_realistic_for_200"), "NO")


if __name__ == "__main__":
    unittest.main()
