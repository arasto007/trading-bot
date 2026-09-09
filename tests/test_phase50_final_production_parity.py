"""Phase 50 final parity tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase47_blocker_closure import PHASE47_JSON, run_phase47_collection
from tradingbot.backtest.phase48_executable_backtest import PHASE48_JSON, run_phase48_collection
from tradingbot.backtest.phase49_final_event_oos_validation import PHASE49_JSON, run_phase49_collection
from tradingbot.backtest.phase50_final_production_parity import (
    PHASE,
    PHASE50_BLOCKERS_MD,
    PHASE50_JSON,
    PHASE50_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase50_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE47_JSON).is_file():
        run_phase47_collection(root)
    if not (root / PHASE48_JSON).is_file():
        run_phase48_collection(root)
    if not (root / PHASE49_JSON).is_file():
        run_phase49_collection(root)
    art = root / PHASE50_JSON
    if art.is_file():
        p = json.loads(art.read_text(encoding="utf-8"))
        if p.get("phase") == PHASE and p.get("production_readiness") == "NOT_READY":
            return
    run_phase50_collection(root)


class TestPhase50(unittest.TestCase):
    def test_not_ready(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE50_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p["production_readiness"], "NOT_READY")
        self.assertEqual(p["FINAL_GATE"], "BLOCKED")
        self.assertFalse(p["verdict"]["ready_for_live"])
        self.assertTrue(p["nogo_for_optimization_or_live"])
        self.assertEqual(p["parity"]["EXECUTION_PARITY"], "FAIL")
        self.assertEqual(p["parity"]["BROKER_PARITY"], "FAIL")
        self.assertFalse(p["env_accessed"])
        self.assertFalse(p["verdict"]["commission_verified"])

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE50_JSON).read_text(encoding="utf-8"))
        for k in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(k, p)
        src = (root / "tradingbot/backtest/phase50_final_production_parity.py").read_text(encoding="utf-8")
        for t in FORBIDDEN:
            self.assertNotIn(t, src)
        self.assertIn("NOT_READY", (root / PHASE50_MD).read_text(encoding="utf-8"))
        self.assertIn("NO-GO", (root / PHASE50_BLOCKERS_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
