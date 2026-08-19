"""Phase 28B — production integration deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase28b"

DELIVERABLES = [
    "integration_validation.json",
    "restart_validation.json",
    "partial_close_validation.json",
    "timeout_validation.json",
    "journal_validation.json",
    "compatibility_validation.json",
    "performance_validation.json",
    "failure_scenarios.json",
    "production_checklist.json",
    "equity_comparison.json",
    "risk_comparison.json",
    "montecarlo_comparison.json",
    "phase28b_final_report.json",
]

VERDICTS = {"PRODUCTION_READY", "PRODUCTION_NOT_READY"}


class TestPhase28BDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase28b_final_report.json").is_file():
            raise unittest.SkipTest("Phase 28B deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase28b_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_integration_modes(self) -> None:
        iv = json.loads((PHASE_DIR / "integration_validation.json").read_text(encoding="utf-8"))
        self.assertIn("HYBRID_B", iv.get("exit_modes_supported") or [])

    def test_compatibility_switch(self) -> None:
        cv = json.loads((PHASE_DIR / "compatibility_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(cv.get("current_mode_works"))
        self.assertTrue(cv.get("hybrid_b_mode_works"))

    def test_failure_scenarios(self) -> None:
        fs = json.loads((PHASE_DIR / "failure_scenarios.json").read_text(encoding="utf-8"))
        self.assertIn("scenarios", fs)

    def test_performance_validation(self) -> None:
        pv = json.loads((PHASE_DIR / "performance_validation.json").read_text(encoding="utf-8"))
        self.assertIn("production_hybrid_b", pv)
        self.assertIn("phase28a_baseline", pv)

    def test_production_checklist(self) -> None:
        pc = json.loads((PHASE_DIR / "production_checklist.json").read_text(encoding="utf-8"))
        self.assertTrue(pc.get("items", {}).get("exit_only_change"))


if __name__ == "__main__":
    unittest.main()
