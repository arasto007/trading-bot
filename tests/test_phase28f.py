"""Phase 28F — accounting unification deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase28f"

DELIVERABLES = [
    "accounting_engine_map.json",
    "duplicate_pnl_report.json",
    "position_sizing_validation.json",
    "broker_constraints.json",
    "risk_validation.json",
    "trade_accounting_validation.json",
    "equity_validation.json",
    "balance_validation.json",
    "portfolio_validation.json",
    "journal_validation.json",
    "performance_validation.json",
    "consistency_audit.json",
    "before_after_comparison.json",
    "phase28f_final_report.json",
]

VERDICTS = {"ACCOUNTING_ENGINE_UNIFIED", "ACCOUNTING_ENGINE_INCONSISTENT"}


class TestPhase28F(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase28f_final_report.json").is_file():
            from tradingbot.ml.research.phase28f.run_investigation import run_phase28f

            run_phase28f()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase28f_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_trade_log_matches_portfolio(self) -> None:
        val = json.loads((PHASE_DIR / "trade_accounting_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(val.get("all_pass"))
        self.assertLessEqual(abs(val["trade_log_net_pnl"] - val["portfolio_net_pnl"]), 0.01)

    def test_pnl_mismatch_eliminated(self) -> None:
        comp = json.loads((PHASE_DIR / "before_after_comparison.json").read_text(encoding="utf-8"))
        before_mismatch = float(comp["before"].get("pnl_mismatch") or 0)
        after_mismatch = float(comp["after"].get("pnl_mismatch") or 0)
        self.assertGreater(before_mismatch, 100.0)
        self.assertLessEqual(after_mismatch, 0.01)

    def test_dynamic_sizing_reported(self) -> None:
        sizing = json.loads((PHASE_DIR / "position_sizing_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(sizing.get("dynamic_sizing_enabled"))
        self.assertGreater(sizing.get("trades_with_min_lot_limit", 0), 0)

    def test_canonical_engine_documented(self) -> None:
        emap = json.loads((PHASE_DIR / "accounting_engine_map.json").read_text(encoding="utf-8"))
        self.assertIn("AccountingEngine", emap.get("canonical_engine", ""))


if __name__ == "__main__":
    unittest.main()
