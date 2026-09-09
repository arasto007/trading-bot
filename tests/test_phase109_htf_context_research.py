"""Phase 109 HTF context tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON, run_phase98_collection
from tradingbot.backtest.phase109_htf_context_research import (
    PHASE,
    PHASE40_JSON,
    PHASE109_JSON,
    PHASE109_MD,
    PREDECLARED,
    REQUIRED_ARTIFACT_KEYS,
    run_phase109_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE98_JSON).is_file():
        run_phase98_collection(root)
    art = root / PHASE109_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("logical_xauusd_used") is False:
            return
    run_phase109_collection(root)


class TestPhase109(unittest.TestCase):
    def test_canonical_m15_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE109_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["logical_xauusd_used"])
        self.assertFalse(payload["strategy_redesigned"])
        self.assertFalse(payload["grid_search"])
        self.assertEqual(list(payload["predeclared_features"]), list(PREDECLARED))
        self.assertIn(
            payload["HTF_DISCRIMINATOR_STATUS"],
            {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "DATA_MISSING", "DATA_LIMITED", "INSUFFICIENT_EVIDENCE"},
        )

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE109_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase109_htf_context_research.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("HTF_DISCRIMINATOR_STATUS", (root / PHASE109_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
