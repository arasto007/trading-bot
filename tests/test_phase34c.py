"""Phase 34C/34D tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase34C(unittest.TestCase):
    def test_marginal_pf_helper(self) -> None:
        from tradingbot.ml.research.phase34c.run_filter_audit import _pf

        self.assertEqual(_pf([2.0, -1.0, 1.0]), 3.0)

    def test_deliverables_after_run(self) -> None:
        report = PROJECT_ROOT / "phase34c_final_report.json"
        if not report.exists():
            self.skipTest("phase34c not yet run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "34C")
        self.assertIn("verdict", data)


class TestPhase34D(unittest.TestCase):
    def test_deliverables_after_run(self) -> None:
        report = PROJECT_ROOT / "phase34d_final_report.json"
        if not report.exists():
            self.skipTest("phase34d not yet run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "34D")
        self.assertIn("engineering_verdict", data)


if __name__ == "__main__":
    unittest.main()
