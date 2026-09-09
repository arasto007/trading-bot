"""Phase 99 path velocity / persistence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON, run_phase98_collection
from tradingbot.backtest.phase99_path_velocity_persistence import (
    PHASE,
    PHASE40_JSON,
    PHASE99_JSON,
    PHASE99_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase99_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE98_JSON).is_file():
        run_phase98_collection(root)
    art = root / PHASE99_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase99_collection(root)


class TestPhase99(unittest.TestCase):
    def test_persistence_kinds(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE99_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["PERSISTENCE_DISCRIMINATOR"], {"OVERLAPPING_DESCRIPTIVE", "CANDIDATE_PERSISTENCE"})
        self.assertFalse(payload["grid_search"])
        self.assertIn("0.5", payload["by_level"])
        kinds = payload["by_level"]["0.5"]["kinds_CD"]
        self.assertEqual(set(kinds), {"FAST_SPIKE", "SUSTAINED_FAVORABLE", "MIXED"})

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE99_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase99_path_velocity_persistence.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("PERSISTENCE_DISCRIMINATOR", (root / PHASE99_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
