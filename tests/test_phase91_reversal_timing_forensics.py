"""Phase 91 reversal timing tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON, run_phase90_collection
from tradingbot.backtest.phase91_reversal_timing_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE91_JSON,
    PHASE91_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase91_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE90_JSON).is_file():
        run_phase90_collection(root)
    art = root / PHASE91_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("timeout_selected") is False:
            return
    run_phase91_collection(root)


class TestPhase91(unittest.TestCase):
    def test_no_timeout_chosen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE91_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["timeout_selected"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertIn("0.5", payload["by_gate"])
        self.assertIn(payload["TIME_AS_CAUSAL_PROTECTION_SIGNAL"], {"UNSUPPORTED", "WEAK_OVERLAP", "PARTIALLY_SUPPORTED", "SUPPORTED"})

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE91_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase91_reversal_timing_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("No timeout chosen", (root / PHASE91_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
