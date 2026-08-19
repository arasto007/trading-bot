"""Final pre-paper audit deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase_final_audit"

DELIVERABLES = [
    "project_structure.json",
    "dependency_graph.json",
    "ownership_graph.json",
    "dead_code.json",
    "call_graph.json",
    "runtime_graph.json",
    "configuration_audit.json",
    "model_audit.json",
    "feature_audit.json",
    "decision_audit.json",
    "risk_audit.json",
    "execution_audit.json",
    "background_services.json",
    "runtime_integrity.json",
    "state_machine.json",
    "failure_surface.json",
    "repository_hygiene.json",
    "integrity_score.json",
    "critical_findings.json",
    "paper_trading_readiness.json",
    "system_integrity_report.json",
    "phase_final_audit.json",
]

VERDICTS = {"SYSTEM_READY_FOR_PAPER", "SYSTEM_NOT_READY_FOR_PAPER"}


class TestFinalAuditDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase_final_audit.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)


if __name__ == "__main__":
    unittest.main()
