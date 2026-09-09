"""Phase 112 non-OHLC discriminator gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase111_multisource_alignment import PHASE111_JSON, run_phase111_collection
from tradingbot.backtest.phase112_non_ohlc_discriminator_gate import (
    GATE_ALLOWED,
    PHASE,
    PHASE40_JSON,
    PHASE112_JSON,
    PHASE112_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase112_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE111_JSON).is_file():
        run_phase111_collection(root)
    art = root / PHASE112_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("expectancy_alone_not_sufficient") is True:
            return
    run_phase112_collection(root)


class TestPhase112(unittest.TestCase):
    def test_gate_classes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE112_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["DISCRIMINATOR_STATUS"], GATE_ALLOWED)
        self.assertTrue(payload["expectancy_alone_not_sufficient"])
        for name in ("tick", "spread", "htf", "news", "multisource"):
            self.assertIn(name, payload["candidates"])
            self.assertIn(payload["candidates"][name]["CLASS"], GATE_ALLOWED)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE112_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase112_non_ohlc_discriminator_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("DISCRIMINATOR_STATUS", (root / PHASE112_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
