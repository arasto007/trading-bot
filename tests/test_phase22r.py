"""Phase 22R — refactor feasibility tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22R(unittest.TestCase):
    def test_deliverables_and_verdict(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22r"
        for name in (
            "current_range_pipeline.json",
            "feature_parity_report.json",
            "dependency_impact.json",
            "refactor_risk_assessment.json",
            "required_file_changes.json",
            "phase22r_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22r run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22r_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(final["verdict"], ("SAFE_TO_REFACTOR", "NOT_SAFE_TO_REFACTOR"))

    def test_feature_builder_registered_features(self):
        from tradingbot.ml.features.builder import FeatureBuilder

        names = FeatureBuilder.registered_feature_names()
        for feat in ("ema50_slope", "candle_direction", "structure_distance"):
            self.assertIn(feat, names)


if __name__ == "__main__":
    unittest.main()
