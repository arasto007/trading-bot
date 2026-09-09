"""Phase 98 first-favorable state tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON, run_phase90_collection
from tradingbot.backtest.phase98_first_favorable_state import (
    PHASE,
    PHASE40_JSON,
    PHASE98_JSON,
    PHASE98_MD,
    REQUIRED_ARTIFACT_KEYS,
    STATE_LEVELS,
    run_phase98_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    if not (root / PHASE90_JSON).is_file():
        run_phase90_collection(root)
    art = root / PHASE98_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase98_collection(root)


class TestPhase98(unittest.TestCase):
    def test_causal_snapshots(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE98_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["n_events"], 419)
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["grid_search"])
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertIn(payload["DISCRIMINATOR_AT_FIRST_FAVORABLE"], {"NOT_ESTABLISHED", "CANDIDATE_BINARY_FEATURES"})
        for lv in STATE_LEVELS:
            self.assertIn(str(lv), payload["by_level"])
        compact = payload["compact"]
        self.assertEqual(len(compact), 419)
        self.assertTrue(any(r.get("path_class") == "F" for r in compact))
        self.assertTrue(any("2026-01-21" in str(r.get("ts")) and r.get("path_class") == "F" for r in compact))

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE98_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase98_first_favorable_state.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("DISCRIMINATOR_AT_FIRST_FAVORABLE", (root / PHASE98_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
