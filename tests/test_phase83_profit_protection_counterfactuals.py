"""Phase 83 structural protection counterfactual tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase82_profit_protection_design import PHASE82_JSON, run_phase82_collection
from tradingbot.backtest.phase83_profit_protection_counterfactuals import (
    PHASE,
    PHASE40_JSON,
    PHASE83_JSON,
    PHASE83_MD,
    REQUIRED_ARTIFACT_KEYS,
    TESTABLE_FAMILIES,
    run_phase83_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
ALLOWED = {"HELPFUL", "NEUTRAL", "HARMFUL", "DATA_LIMITED"}


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    if not (root / PHASE82_JSON).is_file():
        run_phase82_collection(root)
    art = root / PHASE83_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("grid_search") is False:
            return
    run_phase83_collection(root)


class TestPhase83(unittest.TestCase):
    def test_predeclared_families(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE83_JSON).read_text(encoding="utf-8"))
        cfs = payload["counterfactuals"]
        for name in TESTABLE_FAMILIES:
            self.assertIn(cfs[name]["status"], ALLOWED)
            self.assertIn("TRAIN", cfs[name])
            self.assertIn("VALIDATION", cfs[name])
            self.assertIn("OOS", cfs[name])
            self.assertIn("RECENT_180D", cfs[name])
            self.assertIn("by_side", cfs[name])
            self.assertIn("destroyed_extreme_winners", cfs[name])
        self.assertEqual(cfs["ATR_NORMALIZED_RETRACE"]["status"], "DATA_LIMITED")
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["grid_search"])
        if not payload["hybrid_created"]:
            self.assertEqual(cfs["HYBRID"]["status"], "DATA_LIMITED")
        else:
            self.assertGreaterEqual(len(payload["helpful_families"]), 2)
        self.assertTrue(payload["production_safety"]["theoretical_only"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE83_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase83_profit_protection_counterfactuals.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("THEORETICAL", (root / PHASE83_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
