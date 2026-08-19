"""Phase 22T — controlled FeatureBuilder refactor tests."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22T(unittest.TestCase):
    def test_deliverables_and_verdict(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22t"
        for name in (
            "baseline_vs_live.json",
            "signal_comparison.json",
            "trade_comparison.json",
            "feature_source_validation.json",
            "phase22t_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22t run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22t_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(
            final["verdict"],
            ("NO_EFFECT", "SMALL_EFFECT", "SIGNIFICANT_EFFECT", "PRODUCTION_READY"),
        )
        self.assertFalse(final.get("production_modified", True))

    def test_feature_flag_default_off(self):
        from tradingbot.ml.research.phase22t.config import ENV_FLAG, use_live_phase99_features

        os.environ.pop(ENV_FLAG, None)
        self.assertFalse(use_live_phase99_features())

    def test_verdict_no_effect_when_identical(self):
        from tradingbot.ml.research.phase22t.runner import determine_verdict

        row = {
            "BUY": 0, "SELL": 0, "signal_density_pct": 0.0,
            "decision_hold": 100, "trade_count": 0,
            "profit_factor": 0.0, "expectancy": 0.0,
        }
        sig = {"signals": {"BUY": 0, "SELL": 0, "HOLD": 10}, "signal_density_pct": 0.0, "p_win": {"mean": 0.36}}
        self.assertEqual(determine_verdict(row, row, sig, sig), "NO_EFFECT")


if __name__ == "__main__":
    unittest.main()
