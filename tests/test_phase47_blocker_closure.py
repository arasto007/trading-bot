"""Phase 47 blocker-closure tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase47_blocker_closure import (
    PHASE,
    PHASE47_JSON,
    PHASE47_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase47_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE47_JSON
    if art.is_file():
        p = json.loads(art.read_text(encoding="utf-8"))
        if p.get("phase") == PHASE and p.get("commission", {}).get("VERIFIED_SCHEDULE") is False:
            return
    run_phase47_collection(root)


class TestPhase47(unittest.TestCase):
    def test_no_false_closure(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE47_JSON).read_text(encoding="utf-8"))
        self.assertFalse(p["commission"]["VERIFIED_SCHEDULE"])
        self.assertEqual(p["commission"]["status"], "UNKNOWN")
        self.assertFalse(p["commission"]["zero_converted_to_schedule"])
        self.assertEqual(p["symbol"]["EV_EQ_01"], "NOT_PROVEN")
        self.assertEqual(p["request_fill"]["pairs"], 0)
        self.assertFalse(p["request_fill"]["synthetic_pairs_created"])
        self.assertEqual(p["swap"]["HISTORICAL_SWAP"], "UNKNOWN")
        self.assertEqual(p["blockers_closed"], [])
        self.assertGreaterEqual(len(p["blockers_remaining"]), 8)
        self.assertEqual(p["FINAL_GATE"], "BLOCKED")
        self.assertFalse(p["mt5_attached"])
        self.assertFalse(p["env_accessed"])

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE47_JSON).read_text(encoding="utf-8"))
        for k in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(k, p)
        src = (root / "tradingbot/backtest/phase47_blocker_closure.py").read_text(encoding="utf-8")
        for t in FORBIDDEN:
            self.assertNotIn(t, src)
        self.assertIn("VERIFIED_SCHEDULE", (root / PHASE47_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
