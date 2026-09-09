"""Phase 70 exit counterfactual tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase68_exit_forensics import PHASE68_JSON, run_phase68_collection
from tradingbot.backtest.phase70_exit_counterfactuals import (
    PHASE,
    PHASE40_JSON,
    PHASE70_JSON,
    PHASE70_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase70_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE68_JSON).is_file():
        run_phase68_collection(root)
    art = root / PHASE70_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("grid_search") is False:
            return
    run_phase70_collection(root)


class TestPhase70(unittest.TestCase):
    def test_predeclared_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE70_JSON).read_text(encoding="utf-8"))
        self.assertEqual(len(payload["diagnostics_run"]), 9)
        self.assertFalse(payload["grid_search"])
        self.assertFalse(payload["random_search"])
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertFalse(payload["diagnostics"]["B_BREAKEVEN_REACH"]["sl_actually_moved"])
        self.assertGreater(payload["LOSS_AFTER_0_5R"], 100)
        self.assertGreater(payload["LOSS_AFTER_1R"], 50)
        self.assertTrue(payload["stopped_after_predeclared_set"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE70_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase70_exit_counterfactuals.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("COUNTERFACTUAL", (root / PHASE70_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
