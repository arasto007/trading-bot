"""Phase 22Q — repository analysis tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22Q(unittest.TestCase):
    def test_deliverables_exist_after_investigation(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22q"
        for name in (
            "phase99_architecture.json",
            "feature_dependency_map.json",
            "feature_usage_matrix.json",
            "phase99_consumers.json",
            "architecture_verdict.json",
            "phase22q_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22q run_investigation.py first")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data)

    def test_verdict_is_abc_only(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22q" / "architecture_verdict.json"
        if not out.is_file():
            self.skipTest("run investigation first")
        v = json.loads(out.read_text(encoding="utf-8")).get("verdict")
        self.assertIn(v, ("A", "B", "C"))


if __name__ == "__main__":
    unittest.main()
