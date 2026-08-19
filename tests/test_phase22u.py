"""Phase 22U — phase9_9 model capability verification tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22U(unittest.TestCase):
    def test_deliverables_and_verdict(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22u"
        for name in (
            "model_weights.json",
            "training_probability_distribution.json",
            "training_label_distribution.json",
            "probability_histogram.json",
            "model_capability_report.json",
            "phase22u_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22u run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22u_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(
            final["verdict"],
            ("MODEL_DEGENERATED", "MARKET_SPECIFIC", "MODEL_COLLAPSE", "MODEL_HEALTHY"),
        )
        self.assertFalse(final.get("production_modified", True))

    def test_histogram_bins_cover_unit_interval(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22u"
        path = out / "probability_histogram.json"
        if not path.is_file():
            self.skipTest("histogram missing")
        hist = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(hist["bin_width"], 0.05)
        self.assertGreaterEqual(len(hist["bins"]), 20)

    def test_verdict_logic(self):
        from tradingbot.ml.research.phase22u.model_audit import determine_verdict

        zones_no_buy = {"buy_zone_pct": 0.0, "sell_zone_pct": 100.0}
        stats_collapsed = {"std": 0.004, "min": 0.34, "max": 0.38}
        v, _ = determine_verdict(zones_no_buy, stats_collapsed, None)
        self.assertEqual(v, "MODEL_DEGENERATED")


if __name__ == "__main__":
    unittest.main()
