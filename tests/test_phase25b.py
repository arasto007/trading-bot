"""Phase 25B deliverable presence and verdict checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase25b"

DELIVERABLES = [
    "pipeline_depth_comparison.json",
    "timestamp_alignment.json",
    "decision_parity.json",
    "feature_parity.json",
    "probability_parity.json",
    "confidence_parity.json",
    "risk_parity.json",
    "execution_parity.json",
    "timeout_analysis.json",
    "determinism_report.json",
    "root_cause.json",
    "repair_summary.json",
    "phase25b_final_report.json",
]

VERDICTS = {"PARITY_RESTORED", "PARITY_PARTIAL", "PARITY_FAILED"}


class TestPhase25BDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase25b_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)


if __name__ == "__main__":
    unittest.main()
