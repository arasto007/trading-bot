"""Phase 55 cost-scenario tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase54_account_broker_evidence import PHASE54_JSON, run_phase54_collection
from tradingbot.backtest.phase55_cost_scenario_analysis import (
    PHASE,
    PHASE40_JSON,
    PHASE55_JSON,
    PHASE55_MD,
    REQUIRED_ARTIFACT_KEYS,
    commission_r_per_event,
    run_phase55_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE54_JSON).is_file():
        run_phase54_collection(root)
    art = root / PHASE55_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("CLASSIC_SCENARIO_NET_EXPECTANCY") == "UNKNOWN":
            return
    run_phase55_collection(root)


class TestPhase55(unittest.TestCase):
    def test_classic_cent_not_invented(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE55_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["CLASSIC_SCENARIO_NET_EXPECTANCY"], "UNKNOWN")
        self.assertEqual(payload["CENT_SCENARIO_NET_EXPECTANCY"], "UNKNOWN")
        self.assertEqual(payload["scenarios"]["B_CLASSIC"]["CLASSIC_COST_CONVERSION"], "UNKNOWN")
        self.assertEqual(payload["scenarios"]["C_CENT"]["CENT_COST_CONVERSION"], "UNKNOWN")
        self.assertFalse(payload["cost_classes"]["account_specific_verified_cost"])
        self.assertEqual(payload["profitability_verdict"], "NOT_ISSUED")
        self.assertTrue(payload["survival"]["gross_edge_smaller_than_cost_uncertainty"])

    def test_ecn_is_scenario_not_verified(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE55_JSON).read_text(encoding="utf-8"))
        ecn = payload["scenarios"]["A_ECN"]
        self.assertEqual(ecn["commission_per_lot_usd"], 5.0)
        self.assertFalse(ecn["account_verified"])
        self.assertIn("SCENARIO", ecn["label"])
        expected = commission_r_per_event(5.0, 6.86875, 0.01, 1.0)
        self.assertIsNotNone(expected)
        self.assertAlmostEqual(ecn["commission_R_per_event"], expected, places=5)
        self.assertIsInstance(payload["ECN_SCENARIO_NET_EXPECTANCY"], float)
        self.assertEqual(len(payload["sensitivity"]["ecn_usd5_lot_multipliers"]), 6)

    def test_frozen_intact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE55_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["frozen"]["values_overwritten"])
        self.assertFalse(payload["phase40_scan_rerun"])
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase55_cost_scenario_analysis.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("UNKNOWN", (root / PHASE55_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
