"""Phase 48 fail-closed executable tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase47_blocker_closure import PHASE47_JSON, run_phase47_collection
from tradingbot.backtest.phase48_executable_backtest import (
    PHASE,
    PHASE48_JSON,
    PHASE48_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase48_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE47_JSON).is_file():
        run_phase47_collection(root)
    art = root / PHASE48_JSON
    if art.is_file():
        p = json.loads(art.read_text(encoding="utf-8"))
        if p.get("phase") == PHASE and p.get("EXECUTABLE_RESULT") == "BLOCKED":
            return
    run_phase48_collection(root)


class TestPhase48(unittest.TestCase):
    def test_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE48_JSON).read_text(encoding="utf-8"))
        self.assertFalse(p["EXECUTABLE_READY"])
        self.assertEqual(p["EXECUTABLE_RESULT"], "BLOCKED")
        self.assertIsNone(p["GROSS_EXPECTANCY"])
        self.assertIsNone(p["NET_EXPECTANCY"])
        self.assertIsNone(p["TOTAL_COST"])
        self.assertFalse(p["executable"]["ran"])
        self.assertFalse(p["executable"]["simulated_broker_invoked"])
        self.assertFalse(p["prerequisites"]["all_mandatory_met"])
        self.assertFalse(p["prerequisites"]["commission_verified"])
        self.assertIsNone(p["artifacts"]["executable_result_md"])

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE48_JSON).read_text(encoding="utf-8"))
        for k in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(k, p)
        src = (root / "tradingbot/backtest/phase48_executable_backtest.py").read_text(encoding="utf-8")
        for t in FORBIDDEN:
            self.assertNotIn(t, src)
        self.assertIn("BLOCKED", (root / PHASE48_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
