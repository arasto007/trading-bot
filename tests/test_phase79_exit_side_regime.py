"""Phase 79 side/regime exit tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase79_exit_side_regime import (
    PHASE,
    PHASE40_JSON,
    PHASE79_JSON,
    PHASE79_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase79_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    art = root / PHASE79_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase79_collection(root)


class TestPhase79(unittest.TestCase):
    def test_grid_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE79_JSON).read_text(encoding="utf-8"))
        self.assertIn("BUY", payload["by_side"])
        self.assertIn("SELL", payload["by_side"])
        self.assertGreater(len(payload["cells"]), 4)
        self.assertFalse(payload["parameters_optimized"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE79_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase79_exit_side_regime.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("Side x Regime", (root / PHASE79_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
