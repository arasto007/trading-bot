"""Phase 47-48 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase47(unittest.TestCase):
    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase47_final_report.json"
        if not report.exists():
            self.skipTest("phase47 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertIn("best_dataset", data)


class TestPhase48(unittest.TestCase):
    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase48_final_report.json"
        if not report.exists():
            self.skipTest("phase48 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "48")
        status = json.loads((PROJECT_ROOT / "ENGINEERING_STATUS.json").read_text(encoding="utf-8"))
        self.assertEqual(status.get("status"), "PHASE_48_COMPLETE")


if __name__ == "__main__":
    unittest.main()
