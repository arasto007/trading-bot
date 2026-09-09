"""Phase 101 entry quality vs exit failure tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON, run_phase98_collection
from tradingbot.backtest.phase101_entry_vs_exit import (
    PHASE,
    PHASE40_JSON,
    PHASE101_JSON,
    PHASE101_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase101_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE98_JSON).is_file():
        run_phase98_collection(root)
    art = root / PHASE101_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("signal_generation_unchanged") is True:
            return
    run_phase101_collection(root)


class TestPhase101(unittest.TestCase):
    def test_exit_or_entry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE101_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["signal_generation_unchanged"])
        self.assertIn(payload["PROBLEM"], {"EXIT_REMAINS_DOMINANT", "PARTLY_SIGNAL_QUALITY"})
        self.assertEqual(payload["n_CD"] + payload.get("n_A_immediate", 0) >= 0, True)
        self.assertFalse(payload["grid_search"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE101_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase101_entry_vs_exit.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("ENTRY_DISTINGUISHABLE", (root / PHASE101_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
