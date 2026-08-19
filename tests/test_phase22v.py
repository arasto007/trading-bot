"""Phase 22V — training pipeline forensics tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22V(unittest.TestCase):
    def test_deliverables_and_verdict(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22v"
        for name in (
            "training_pipeline_map.json",
            "feature_statistics.json",
            "feature_predictiveness.json",
            "training_process.json",
            "convergence_report.json",
            "root_cause_report.json",
            "phase22v_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22v run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22v_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(
            final["verdict"],
            (
                "BAD_DATA", "BAD_FEATURES", "BAD_LABELS",
                "BAD_TRAINING", "BAD_MODEL_CHOICE", "MULTIPLE_CAUSES", "MODEL_HEALTHY",
            ),
        )
        self.assertFalse(final.get("production_modified", True))

    def test_pipeline_has_freeze_stage(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22v"
        path = out / "training_pipeline_map.json"
        if not path.is_file():
            self.skipTest("pipeline map missing")
        data = json.loads(path.read_text(encoding="utf-8"))
        names = [s.get("name", "") for s in data.get("stages", [])]
        self.assertTrue(any("Freeze" in n for n in names))


if __name__ == "__main__":
    unittest.main()
