"""Phase 106 non-OHLC inventory tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase106_non_ohlc_data_inventory import (
    CLASSES,
    PHASE,
    PHASE40_JSON,
    PHASE106_JSON,
    PHASE106_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase106_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE106_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("downloaded") is False:
            return
    run_phase106_collection(root)


class TestPhase106(unittest.TestCase):
    def test_inventory_classes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE106_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["mt5_launched"])
        self.assertFalse(payload["downloaded"])
        self.assertFalse(payload["env_accessed"])
        self.assertEqual(payload["n_events"], 419)
        for row in payload["inventory"]:
            self.assertIn(row["class"], CLASSES)
        self.assertEqual(payload["by_category"]["news"], "MISSING")
        self.assertEqual(payload["by_category"]["economic_calendar"], "MISSING")

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE106_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase106_non_ohlc_data_inventory.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("NON_OHLC_DATA_STATUS", (root / PHASE106_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
