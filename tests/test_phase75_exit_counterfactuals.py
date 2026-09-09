"""Phase 75 exit counterfactual tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase75_exit_counterfactuals import (
    PHASE,
    PHASE40_JSON,
    PHASE75_JSON,
    PHASE75_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase75_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    art = root / PHASE75_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("grid_search") is False:
            return
    run_phase75_collection(root)


class TestPhase75(unittest.TestCase):
    def test_predeclared_theoretical(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE75_JSON).read_text(encoding="utf-8"))
        self.assertEqual(len(payload["diagnostics_run"]), 7)
        self.assertFalse(payload["grid_search"])
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertTrue(payload["best_is_not_optimal"])
        self.assertEqual(payload["counterfactuals"]["F_REGIME_INVALIDATION_EXIT"]["status"], "DATA_LIMITED")
        self.assertEqual(payload["counterfactuals"]["G_SIGNAL_INVALIDATION_EXIT"]["status"], "DATA_LIMITED")
        for name in ("A_BREAKEVEN_AFTER_0_5R", "B_BREAKEVEN_AFTER_1R", "C_LOCK_0_25R_AFTER_1R", "D_LOCK_0_5R_AFTER_1R"):
            self.assertIn(payload["counterfactuals"][name]["status"], {"HELPFUL", "NEUTRAL", "HARMFUL", "DATA_LIMITED"})
        self.assertFalse(payload["production_safety"]["production_sl_moved"] if "production_sl_moved" in payload["production_safety"] else False)
        self.assertTrue(payload["production_safety"]["theoretical_only"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE75_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase75_exit_counterfactuals.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("THEORETICAL", (root / PHASE75_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
