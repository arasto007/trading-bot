"""Phase 27B deliverable presence and evidence structure checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27b"

DELIVERABLES = [
    "filter_location.json",
    "rsi_hold_log.json",
    "buy_sell_filter_statistics.json",
    "pre_post_filter_statistics.json",
    "distribution_analysis.json",
    "threshold_sensitivity.json",
    "stage_funnel.json",
    "feature_quality.json",
    "engine_statistics.json",
    "root_cause_rank.json",
    "final_report.json",
]


class TestPhase27BDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_filter_location_has_caller(self) -> None:
        doc = json.loads((PHASE_DIR / "filter_location.json").read_text(encoding="utf-8"))
        self.assertEqual(doc.get("function"), "apply_profitability_filters")
        self.assertIn("caller", doc)
        self.assertIn("formula", doc)

    def test_final_report_read_only(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertTrue(report.get("production_modified") is False)
        self.assertEqual(report.get("audit_mode"), "READ_ONLY")
        self.assertIn(report.get("verdict"), {"MULTIPLE_ROOT_CAUSES"})
        self.assertTrue(report.get("ranked_causes"))

    def test_rsi_hold_log_structure(self) -> None:
        log = json.loads((PHASE_DIR / "rsi_hold_log.json").read_text(encoding="utf-8"))
        self.assertIn("total_blocked", log)
        self.assertIn("records", log)
        if log["records"]:
            row = log["records"][0]
            for key in (
                "timestamp",
                "decision_before_rsi",
                "decision_after_rsi",
                "rsi",
                "reason",
            ):
                self.assertIn(key, row)

    def test_root_cause_has_evidence(self) -> None:
        ranked = json.loads((PHASE_DIR / "root_cause_rank.json").read_text(encoding="utf-8"))
        causes = ranked.get("ranked_causes") or []
        self.assertGreaterEqual(len(causes), 2)
        for cause in causes:
            self.assertIn("severity", cause)
            self.assertIn("repository_location", cause)
            self.assertIn("runtime_evidence", cause)
            self.assertIn("recommended_fix", cause)


if __name__ == "__main__":
    unittest.main()
