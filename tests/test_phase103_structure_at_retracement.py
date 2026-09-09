"""Phase 103 structure-at-retracement tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON, run_phase98_collection
from tradingbot.backtest.phase103_structure_at_retracement import (
    PHASE,
    PHASE40_JSON,
    PHASE103_JSON,
    PHASE103_MD,
    PREDECLARED_CONCEPTS,
    REQUIRED_ARTIFACT_KEYS,
    run_phase103_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE98_JSON).is_file():
        run_phase98_collection(root)
    art = root / PHASE103_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase103_collection(root)


class TestPhase103(unittest.TestCase):
    def test_predeclared_concepts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE103_JSON).read_text(encoding="utf-8"))
        self.assertEqual(list(payload["predeclared_concepts"]), list(PREDECLARED_CONCEPTS))
        self.assertIn(payload["STRUCTURAL_DISCRIMINATOR"], {"NOT_ESTABLISHED", "TRAIN_VAL_ONLY", "SPLIT_SURVIVOR"})
        self.assertFalse(payload["grid_search"])
        self.assertFalse(payload["oos_used_for_selection"])
        for feat in PREDECLARED_CONCEPTS:
            self.assertIn(feat, payload["features"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE103_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase103_structure_at_retracement.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("STRUCTURAL_DISCRIMINATOR", (root / PHASE103_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
