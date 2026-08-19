"""Phase 22S — FeatureBuilder numerical parity certification tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22S(unittest.TestCase):
    def test_deliverables_and_verdict(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22s"
        for name in (
            "feature_value_parity.json",
            "window_sensitivity.json",
            "feature_statistics.json",
            "minimum_history_required.json",
            "phase22s_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22s run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22s_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(
            final["verdict"],
            ("NUMERICAL_PARITY_PROVEN", "PARTIAL_PARITY", "PARITY_FAILED"),
        )
        self.assertFalse(final.get("production_modified", True))

    def test_parity_compared_most_rows(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22s"
        parity_path = out / "feature_value_parity.json"
        if not parity_path.is_file():
            self.skipTest("parity report missing")
        parity = json.loads(parity_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(parity["rows_compared"], 5000)
        for feat in ("ema50_slope", "candle_direction", "structure_distance"):
            self.assertIn(feat, parity["feature_statistics"])

    def test_determine_verdict_logic(self):
        from tradingbot.ml.research.phase22s.parity_cert import determine_verdict

        perfect = {
            "ema50_slope": {"exact_match_pct": 100.0},
            "candle_direction": {"exact_match_pct": 100.0},
            "structure_distance": {"exact_match_pct": 100.0},
        }
        self.assertEqual(determine_verdict(perfect), "NUMERICAL_PARITY_PROVEN")
        partial = dict(perfect)
        partial["ema50_slope"] = {"exact_match_pct": 99.91}
        self.assertEqual(determine_verdict(partial), "PARTIAL_PARITY")


if __name__ == "__main__":
    unittest.main()
