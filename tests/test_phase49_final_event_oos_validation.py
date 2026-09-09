"""Phase 49 robustness tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase47_blocker_closure import PHASE47_JSON, run_phase47_collection
from tradingbot.backtest.phase48_executable_backtest import PHASE48_JSON, run_phase48_collection
from tradingbot.backtest.phase49_final_event_oos_validation import (
    ALLOWED_VERDICTS,
    PHASE,
    PHASE49_JSON,
    PHASE49_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase49_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(")


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE47_JSON).is_file():
        run_phase47_collection(root)
    if not (root / PHASE48_JSON).is_file():
        run_phase48_collection(root)
    art = root / PHASE49_JSON
    if art.is_file():
        p = json.loads(art.read_text(encoding="utf-8"))
        if p.get("phase") == PHASE and p.get("robustness_verdict") in ALLOWED_VERDICTS:
            return
    run_phase49_collection(root)


class TestPhase49(unittest.TestCase):
    def test_fragile_nogo(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE49_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p["events"]["event_count"], 420)
        self.assertEqual(p["oos"]["oos_signals"], 367)
        self.assertEqual(p["oos"]["oos_events"], 63)
        self.assertFalse(p["boundaries_changed"])
        self.assertFalse(p["parameters_optimized"])
        self.assertFalse(p["cost_aware"]["validated"])
        self.assertFalse(p["cost_aware"]["phase48_ran"])
        self.assertEqual(p["robustness_verdict"], "FRAGILE")
        self.assertTrue(p["nogo_for_optimization_or_live"])
        self.assertEqual(p["FINAL_GATE"], "BLOCKED")

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE49_JSON).read_text(encoding="utf-8"))
        for k in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(k, p)
        src = (root / "tradingbot/backtest/phase49_final_event_oos_validation.py").read_text(encoding="utf-8")
        for t in FORBIDDEN:
            self.assertNotIn(t, src)
        self.assertIn("FRAGILE", (root / PHASE49_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
