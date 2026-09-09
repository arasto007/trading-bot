"""Phase 74 profit-giveback forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE74_JSON,
    PHASE74_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase74_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE74_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase74_collection(root)


class TestPhase74(unittest.TestCase):
    def test_giveback_classes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE74_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["n_resolved"], 419)
        self.assertEqual(payload["LOSS_SL"], 298)
        self.assertEqual(payload["LOSS_AFTER_0_5R"], 157)
        self.assertEqual(payload["LOSS_AFTER_1R"], 94)
        self.assertGreater(payload["PROFIT_GIVEBACK_RATE"], 0.5)
        self.assertGreater(payload["loser_classes"]["L3"]["count"], 100)
        self.assertFalse(payload["parameters_optimized"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE74_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase74_profit_giveback_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertEqual(payload["production_safety"]["SL_TP"], "NOT_CHANGED")
        self.assertIn("PROFIT_GIVEBACK_RATE", (root / PHASE74_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
