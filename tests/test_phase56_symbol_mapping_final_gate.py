"""Phase 56 information-value gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase54_account_broker_evidence import PHASE54_JSON, run_phase54_collection
from tradingbot.backtest.phase55_cost_scenario_analysis import PHASE55_JSON, run_phase55_collection
from tradingbot.backtest.phase56_symbol_mapping_final_gate import (
    PHASE,
    PHASE40_JSON,
    PHASE54_56_MD,
    PHASE56_JSON,
    PHASE56_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase56_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE54_JSON).is_file():
        run_phase54_collection(root)
    if not (root / PHASE55_JSON).is_file():
        run_phase55_collection(root)
    art = root / PHASE56_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("OPTIMIZATION_ALLOWED") is False:
            return
    run_phase56_collection(root)


class TestPhase56(unittest.TestCase):
    def test_gates_and_no_go(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE56_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["FINAL_GATE"], "BLOCKED")
        self.assertFalse(payload["OPTIMIZATION_ALLOWED"])
        self.assertFalse(payload["LIVE_TRADING_ALLOWED"])
        self.assertFalse(payload["project_stopped"])
        self.assertEqual(payload["gates"]["G2_COMMISSION_SCHEDULE_VERIFIED"]["status"], "FAIL")
        self.assertEqual(payload["gates"]["G7_EXECUTABLE_COST_AWARE_BACKTEST"]["status"], "FAIL")
        self.assertGreaterEqual(len(payload["NEXT_BEST_ACTIONS"]), 3)
        self.assertEqual(payload["telemetry"]["LIVE_CAPTURE_NOT_ACTIVE"], True)
        self.assertFalse(payload["telemetry"]["wired_into_live"])
        self.assertFalse(payload["telemetry"]["HISTORICAL_AVAILABLE"])

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE56_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase56_symbol_mapping_final_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("NEXT_BEST_ACTIONS", (root / PHASE56_MD).read_text(encoding="utf-8"))
        self.assertIn("GO CONDITIONS", (root / PHASE54_56_MD).read_text(encoding="utf-8"))
        self.assertFalse(payload["env_accessed"])


if __name__ == "__main__":
    unittest.main()
