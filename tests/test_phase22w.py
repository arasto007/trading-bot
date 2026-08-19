"""Phase 22W — selection criterion audit tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22W(unittest.TestCase):
    def test_deliverables_and_verdict(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22w"
        for name in (
            "model_selection_pipeline.json",
            "candidate_ranking.json",
            "candidate_probability_analysis.json",
            "selection_criteria_audit.json",
            "first_engineering_mistake.json",
            "phase22w_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22w run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22w_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "MODEL_SELECTION_CRITERIA")

    def test_no_probability_gates_in_code_audit(self):
        from tradingbot.ml.research.phase22w.selection_audit import audit_selection_criteria

        audit = audit_selection_criteria()
        absent = audit["probability_quality_gates_absent"]
        self.assertTrue(all(absent.values()))


if __name__ == "__main__":
    unittest.main()
