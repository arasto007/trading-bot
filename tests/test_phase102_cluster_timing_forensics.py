"""Phase 102 event cluster / signal timing tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON, run_phase98_collection
from tradingbot.backtest.phase102_cluster_timing_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE102_JSON,
    PHASE102_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase102_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE98_JSON).is_file():
        run_phase98_collection(root)
    art = root / PHASE102_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("signals_not_independent") is True:
            return
    run_phase102_collection(root)


class TestPhase102(unittest.TestCase):
    def test_event_unit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE102_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["signals_not_independent"])
        self.assertEqual(payload["n_events"], 419)
        self.assertEqual(payload["n_raw_signals"], 2847)
        self.assertIn(payload["CLUSTER_EARLY_WARNING"], {"NOT_ESTABLISHED", "CANDIDATE_CLUSTER_TIMING"})
        self.assertFalse(payload["grid_search"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE102_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase102_cluster_timing_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("CLUSTER_EARLY_WARNING", (root / PHASE102_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
