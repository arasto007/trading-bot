"""Phase 26B deliverable presence and verdict checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase26b"

DELIVERABLES = [
    "sample_validation.json",
    "performance_metrics.json",
    "confidence_analysis.json",
    "regime_analysis.json",
    "engine_analysis.json",
    "time_analysis.json",
    "risk_analysis.json",
    "stability_analysis.json",
    "minimum_sample_report.json",
    "phase26b_final_report.json",
]

VERDICTS = {"INSUFFICIENT_SAMPLE", "READY_FOR_OPTIMIZATION"}


class TestPhase26BDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase26b_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_insufficient_sample_when_below_threshold(self) -> None:
        report = json.loads((PHASE_DIR / "phase26b_final_report.json").read_text(encoding="utf-8"))
        minimum = json.loads((PHASE_DIR / "minimum_sample_report.json").read_text(encoding="utf-8"))
        if minimum.get("completed_trades", 0) < minimum.get("minimum_required", 200):
            self.assertEqual(report.get("verdict"), "INSUFFICIENT_SAMPLE")


if __name__ == "__main__":
    unittest.main()
