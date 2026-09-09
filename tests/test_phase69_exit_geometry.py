"""Phase 69 exit geometry tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase68_exit_forensics import PHASE68_JSON, run_phase68_collection
from tradingbot.backtest.phase69_exit_geometry import (
    PHASE,
    PHASE40_JSON,
    PHASE69_JSON,
    PHASE69_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase69_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE68_JSON).is_file():
        run_phase68_collection(root)
    art = root / PHASE69_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("code_modified") is False:
            return
    run_phase69_collection(root)


class TestPhase69(unittest.TestCase):
    def test_hybrid_geometry_and_extreme_class(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE69_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["source_contains_hybrid_max"])
        self.assertEqual(payload["geometry"]["SL_generation"]["type"], "hybrid")
        self.assertEqual(payload["geometry"]["TP_generation"]["type"], "hybrid")
        self.assertFalse(payload["geometry"]["hardening_changes_sl_tp"])
        self.assertTrue(payload["extreme_winner"]["same_exit_generation_mechanism"])
        self.assertEqual(payload["EXTREME_WINNER_CLASSIFICATION"], "B_RARE_LEGITIMATE_STRUCTURAL")
        self.assertFalse(payload["code_modified"])
        self.assertFalse(payload["parameters_optimized"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE69_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase69_exit_geometry.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("EXTREME_WINNER_CLASSIFICATION", (root / PHASE69_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
