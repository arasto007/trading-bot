"""Phase 108 spread-path tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase106_non_ohlc_data_inventory import PHASE106_JSON, run_phase106_collection
from tradingbot.backtest.phase108_spread_path_research import (
    ALLOWED,
    PHASE,
    PHASE40_JSON,
    PHASE108_JSON,
    PHASE108_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase108_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE106_JSON).is_file():
        run_phase106_collection(root)
    art = root / PHASE108_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase108_collection(root)


class TestPhase108(unittest.TestCase):
    def test_status_allowed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE108_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["SPREAD_DISCRIMINATOR_STATUS"], ALLOWED)
        self.assertFalse(payload["grid_search"])
        self.assertFalse(payload["mt5_launched"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE108_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase108_spread_path_research.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("SPREAD_DISCRIMINATOR_STATUS", (root / PHASE108_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
