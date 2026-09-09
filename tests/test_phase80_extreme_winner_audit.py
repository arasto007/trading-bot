"""Phase 80 extreme-winner audit tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase75_exit_counterfactuals import PHASE75_JSON, run_phase75_collection
from tradingbot.backtest.phase80_extreme_winner_audit import (
    PHASE,
    PHASE40_JSON,
    PHASE80_JSON,
    PHASE80_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase80_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    if not (root / PHASE75_JSON).is_file():
        run_phase75_collection(root)
    art = root / PHASE80_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase80_collection(root)


class TestPhase80(unittest.TestCase):
    def test_winner_kept(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE80_JSON).read_text(encoding="utf-8"))
        self.assertIn("2026-01-21", str(payload["winner"]["timestamp"]))
        self.assertTrue(payload["winner"]["kept_in_baseline"])
        self.assertFalse(payload["production_safety"]["baseline_rewritten"])
        self.assertGreaterEqual(payload["rr_gt10_n"], 2)
        self.assertIn("LEGITIMATE", payload["EXTREME_WINNER_STATUS"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE80_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase80_extreme_winner_audit.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("EXTREME_WINNER_STATUS", (root / PHASE80_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
