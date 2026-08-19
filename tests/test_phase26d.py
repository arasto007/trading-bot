"""Phase 26D deliverable presence and verdict checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase26d"

DELIVERABLES = [
    "startup_contract.json",
    "startup_validation.json",
    "configuration_matrix.json",
    "environment_matrix.json",
    "fail_fast_rules.json",
    "diagnostic_report_schema.json",
    "startup_state_machine.json",
    "configuration_conflicts.json",
    "rollback_validation.json",
    "phase26d_final_report.json",
]

VERDICTS = {"STARTUP_SAFE", "STARTUP_NOT_SAFE"}


class TestPhase26DDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase26d_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_no_silent_scenarios(self) -> None:
        payload = json.loads((PHASE_DIR / "startup_validation.json").read_text(encoding="utf-8"))
        self.assertEqual(payload.get("silent_count"), 0)


if __name__ == "__main__":
    unittest.main()
