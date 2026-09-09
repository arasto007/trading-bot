"""Phase 110 news context tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase110_news_context_research import (
    ALLOWED,
    PHASE,
    PHASE40_JSON,
    PHASE110_JSON,
    PHASE110_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase110_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE110_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("external_api") is False:
            return
    run_phase110_collection(root)


class TestPhase110(unittest.TestCase):
    def test_no_fabricated_news(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE110_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["NEWS_DISCRIMINATOR_STATUS"], ALLOWED)
        self.assertFalse(payload["external_api"])
        self.assertFalse(payload["analyzed"])
        self.assertEqual(payload["NEWS_DISCRIMINATOR_STATUS"], "DATA_MISSING")

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE110_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase110_news_context_research.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("NEWS_DISCRIMINATOR_STATUS", (root / PHASE110_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
