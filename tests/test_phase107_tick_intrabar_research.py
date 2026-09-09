"""Phase 107 tick/intrabar tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase106_non_ohlc_data_inventory import PHASE106_JSON, run_phase106_collection
from tradingbot.backtest.phase107_tick_intrabar_research import (
    PHASE,
    PHASE40_JSON,
    PHASE107_JSON,
    PHASE107_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase107_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE106_JSON).is_file():
        run_phase106_collection(root)
    art = root / PHASE107_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase107_collection(root)


class TestPhase107(unittest.TestCase):
    def test_no_fabricated_ticks(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE107_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["TICK_DISCRIMINATOR_STATUS"], {"DATA_MISSING", "INSUFFICIENT_EVIDENCE", "UNSUPPORTED"})
        self.assertFalse(payload["grid_search"])
        self.assertFalse(payload["mt5_launched"])
        if payload["TICK_DISCRIMINATOR_STATUS"] == "DATA_MISSING":
            self.assertFalse(payload["analyzed"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE107_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase107_tick_intrabar_research.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("TICK_DISCRIMINATOR_STATUS", (root / PHASE107_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
