"""Phase 25A deliverable presence checks (read-only audit artifacts)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase25a"

DELIVERABLES = [
    "paper_vs_research.json",
    "decision_parity.json",
    "feature_parity.json",
    "probability_parity.json",
    "risk_parity.json",
    "execution_parity.json",
    "difference_report.json",
    "root_cause.json",
    "phase25a_final_report.json",
]

VERDICTS = {"PAPER_IDENTICAL_TO_RESEARCH", "PAPER_DIFFERS_FROM_RESEARCH"}


class TestPhase25ADeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase25a_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)


if __name__ == "__main__":
    unittest.main()
