"""Phase 63 next-step gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE61_JSON, run_phase61_collection
from tradingbot.backtest.phase62_operator_action_economics import PHASE62_JSON, run_phase62_collection
from tradingbot.backtest.phase63_next_step_gate import (
    ALLOWED_NEXT,
    OPERATOR_MD,
    PHASE,
    PHASE40_JSON,
    PHASE61_63_MD,
    PHASE63_JSON,
    PHASE63_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase63_collection,
    select_next_phase,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE61_JSON).is_file():
        run_phase61_collection(root)
    if not (root / PHASE62_JSON).is_file():
        run_phase62_collection(root)
    art = root / PHASE63_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("OPTIMIZATION_ALLOWED") is False:
            return
    run_phase63_collection(root)


class TestPhase63(unittest.TestCase):
    def test_next_phase_rules(self) -> None:
        nxt, _ = select_next_phase(g1="PARTIAL", g2="PARTIAL", g3="FAIL", quality="FRAGILE", decision="NO_VALUE_CURRENTLY")
        self.assertEqual(nxt, "STRATEGY_RESEARCH_BEFORE_BROKER_WORK")
        nxt2, _ = select_next_phase(g1="PASS", g2="PASS", g3="PASS", quality="STRONG", decision="YES_HIGH_VALUE")
        self.assertEqual(nxt2, "EXECUTABLE_COST_AWARE_VALIDATION")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE63_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["NEXT_PHASE"], ALLOWED_NEXT)
        self.assertNotEqual(payload["NEXT_PHASE"], "EXECUTABLE_COST_AWARE_VALIDATION")
        self.assertFalse(payload["OPTIMIZATION_ALLOWED"])
        self.assertFalse(payload["SHADOW_ALLOWED"])
        self.assertFalse(payload["LIVE_TRADING_ALLOWED"])
        self.assertFalse(payload["project_stopped"])
        op = (root / OPERATOR_MD).read_text(encoding="utf-8")
        self.assertIn("ECN", op)
        self.assertIn("password", op.lower())
        self.assertIn("full account number", op.lower())

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE63_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase63_next_step_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertFalse(payload["env_accessed"])
        self.assertIn("WHAT_NOT_TO_DO", (root / PHASE61_63_MD).read_text(encoding="utf-8"))
        self.assertIn("NEXT_PHASE", (root / PHASE63_MD).read_text(encoding="utf-8"))
        self.assertFalse(payload["prior_sources"]["mutated"])


if __name__ == "__main__":
    unittest.main()
