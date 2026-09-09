"""Phase 71 extreme-winner forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase68_exit_forensics import PHASE68_JSON, run_phase68_collection
from tradingbot.backtest.phase69_exit_geometry import PHASE69_JSON, run_phase69_collection
from tradingbot.backtest.phase71_extreme_winner_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE71_JSON,
    PHASE71_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase71_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE68_JSON).is_file():
        run_phase68_collection(root)
    if not (root / PHASE69_JSON).is_file():
        run_phase69_collection(root)
    art = root / PHASE71_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase71_collection(root)


class TestPhase71(unittest.TestCase):
    def test_outlier_kept_and_classified(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE71_JSON).read_text(encoding="utf-8"))
        self.assertIn("2026-01-21", str(payload["winner"]["timestamp"]))
        self.assertTrue(payload["winner"]["kept_in_official_baseline"])
        self.assertGreater(payload["rr_tails"]["gt_3"]["n"], 10)
        self.assertGreaterEqual(payload["rr_tails"]["gt_10"]["n"], 1)
        self.assertEqual(payload["realized_R_ge10_n"], 1)
        self.assertTrue(payload["isolated_realized_R_ge10"])
        self.assertFalse(payload["isolated_planned_rr_gt10"])
        self.assertEqual(payload["EXTREME_WINNER_CLASSIFICATION"], "B_RARE_LEGITIMATE_STRUCTURAL")
        self.assertLess(payload["TOP1_REMOVAL_EXPECTANCY"], 0)
        self.assertTrue(payload["outlier_robustness"]["official_baseline_unchanged"])
        self.assertFalse(payload["production_safety"]["baseline_rewritten"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE71_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase71_extreme_winner_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("EXTREME_WINNER_CLASSIFICATION", (root / PHASE71_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
