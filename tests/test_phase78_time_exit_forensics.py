"""Phase 78 time-exit forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase78_time_exit_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE78_JSON,
    PHASE78_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase78_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    art = root / PHASE78_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("threshold_search") is False:
            return
    run_phase78_collection(root)


class TestPhase78(unittest.TestCase):
    def test_time_dependency_not_searched(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE78_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["threshold_search"])
        self.assertIn(payload["TIME_DEPENDENCY"], {"PRIMARY", "SECONDARY", "WEAK", "UNSUPPORTED"})
        self.assertEqual(payload["loss_after_0.5R"]["n"], 157)
        self.assertEqual(payload["loss_after_1R"]["n"], 94)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE78_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase78_time_exit_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("TIME_DEPENDENCY", (root / PHASE78_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
