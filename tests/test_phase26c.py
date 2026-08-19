"""Phase 26C deliverable presence and verdict checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase26c"

DELIVERABLES = [
    "journal_flow.json",
    "journal_schema.json",
    "field_integrity.json",
    "fill_price_analysis.json",
    "trade_lifecycle.json",
    "sqlite_validation.json",
    "replay_validation.json",
    "root_cause.json",
    "repair_summary.json",
    "phase26c_final_report.json",
]

VERDICTS = {"JOURNAL_READY", "JOURNAL_NOT_READY"}


class TestPhase26CDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase26c_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_field_completeness(self) -> None:
        report = json.loads((PHASE_DIR / "phase26c_final_report.json").read_text(encoding="utf-8"))
        if report.get("verdict") != "JOURNAL_READY":
            return
        self.assertEqual(report.get("field_completeness_pct"), 100.0)
        self.assertEqual(report.get("zero_fill_count"), 0)
        self.assertGreaterEqual(report.get("simulated_trades", 0), 100)


if __name__ == "__main__":
    unittest.main()
