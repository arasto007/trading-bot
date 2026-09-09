"""Phase 58 commission accountability tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase55_cost_scenario_analysis import commission_r_per_event
from tradingbot.backtest.phase57_account_product_forensics import PHASE57_JSON, run_phase57_collection
from tradingbot.backtest.phase58_commission_accountability import (
    PHASE,
    PHASE40_JSON,
    PHASE58_JSON,
    PHASE58_MD,
    REQUIRED_ARTIFACT_KEYS,
    points_markup_r,
    run_phase58_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE57_JSON).is_file():
        run_phase57_collection(root)
    art = root / PHASE58_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("deals", {}).get("zero_converted_to_schedule") is False:
            return
    run_phase58_collection(root)


class TestPhase58(unittest.TestCase):
    def test_zeros_are_not_a_schedule(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE58_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["deals"]["NOT_PROVEN_SCHEDULE"])
        self.assertFalse(payload["deals"]["zero_converted_to_schedule"])
        self.assertNotEqual(payload["G2"], "PASS")
        self.assertEqual(payload["profitability_verdict"], "NOT_ISSUED")

    def test_classic_not_treated_as_usd14_without_units(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE58_JSON).read_text(encoding="utf-8"))
        classic = payload["scenarios"]["CLASSIC_DOCUMENTED_14"]
        self.assertFalse(classic["treated_as_usd14_without_units"])
        self.assertIn("points", classic["official_units"])
        self.assertAlmostEqual(classic["commission_cost_event_R"], points_markup_r(14.0, 0.01, 6.86875) or 0.0, places=6)
        ecn = payload["scenarios"]["ECN_5_PER_LOT"]
        self.assertFalse(ecn["account_product_verified"])
        self.assertFalse(ecn["commission_schedule_verified"])
        expected = commission_r_per_event(5.0, 6.86875, 0.01, 1.0)
        self.assertAlmostEqual(ecn["commission_cost_event_R"], expected or 0.0, places=6)
        self.assertEqual(len(payload["sensitivity"]), 8)
        self.assertTrue(payload["margin"]["EDGE_SMALLER_THAN_COST_UNCERTAINTY"])
        self.assertIsNone(payload["break_even"]["usd_per_event"])
        self.assertIn("SCENARIO", classic["label"])

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE58_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase58_commission_accountability.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("NOT_PROVEN_SCHEDULE", (root / PHASE58_MD).read_text(encoding="utf-8"))
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["phase40_scan_rerun"])


if __name__ == "__main__":
    unittest.main()
