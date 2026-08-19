"""Phase 26A deliverable presence and verdict checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase26a"

DELIVERABLES = [
    "trade_log.json",
    "daily_statistics.json",
    "weekly_statistics.json",
    "monthly_statistics.json",
    "equity_curve.json",
    "drawdown_curve.json",
    "trade_sequence.json",
    "range_statistics.json",
    "trend_statistics.json",
    "transition_statistics.json",
    "phase99_statistics.json",
    "validation_report.json",
    "phase26a_final_report.json",
]

VERDICTS = {"READY_FOR_PAPER_COLLECTION", "VALIDATION_FAILED"}

REQUIRED_TRADE_FIELDS = {
    "timestamp",
    "symbol",
    "regime",
    "engine",
    "direction",
    "confidence",
    "sl",
    "tp",
    "lot",
    "exit_reason",
    "pnl",
    "pnl_r",
    "duration_bars",
    "mae",
    "mfe",
}


class TestPhase26ADeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase26a_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_trade_log_schema(self) -> None:
        payload = json.loads((PHASE_DIR / "trade_log.json").read_text(encoding="utf-8"))
        if payload.get("count", 0) == 0:
            return
        trade = payload["trades"][0]
        missing = REQUIRED_TRADE_FIELDS - set(trade.keys())
        self.assertFalse(missing, msg=f"missing fields: {missing}")


if __name__ == "__main__":
    unittest.main()
