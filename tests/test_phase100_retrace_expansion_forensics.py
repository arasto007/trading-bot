"""Phase 100 retrace-then-expansion tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON, run_phase98_collection
from tradingbot.backtest.phase100_retrace_expansion_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE100_JSON,
    PHASE100_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase100_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE98_JSON).is_file():
        run_phase98_collection(root)
    art = root / PHASE100_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("outlier_kept") is True:
            return
    run_phase100_collection(root)


class TestPhase100(unittest.TestCase):
    def test_outlier_kept(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE100_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["outlier_kept"])
        self.assertIn("2026-01-21", str(payload.get("outlier_ts")))
        self.assertIn(payload["PRE_RETRACE_DISCRIMINATOR"], {"NOT_ESTABLISHED", "AT_RETRACE_CANDIDATE"})
        self.assertIn("FAILURE", payload["cohorts"])
        self.assertFalse(payload["grid_search"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE100_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase100_retrace_expansion_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("PRE_RETRACE_DISCRIMINATOR", (root / PHASE100_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
