"""Phase 60 unified evidence-gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase57_account_product_forensics import PHASE57_JSON, run_phase57_collection
from tradingbot.backtest.phase58_commission_accountability import PHASE58_JSON, run_phase58_collection
from tradingbot.backtest.phase59_symbol_equivalence_forensics import PHASE59_JSON, run_phase59_collection
from tradingbot.backtest.phase60_unified_evidence_gate import (
    OPERATOR_MD,
    PHASE,
    PHASE40_JSON,
    PHASE57_60_MD,
    PHASE60_JSON,
    PHASE60_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase60_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE57_JSON).is_file():
        run_phase57_collection(root)
    if not (root / PHASE58_JSON).is_file():
        run_phase58_collection(root)
    if not (root / PHASE59_JSON).is_file():
        run_phase59_collection(root)
    art = root / PHASE60_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("OPTIMIZATION_ALLOWED") is False:
            return
    run_phase60_collection(root)


class TestPhase60(unittest.TestCase):
    def test_core_gates_do_not_authorize_executable_or_live(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE60_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["FINAL_GATE"], "BLOCKED")
        self.assertFalse(payload["OPTIMIZATION_ALLOWED"])
        self.assertFalse(payload["SHADOW_ALLOWED"])
        self.assertFalse(payload["LIVE_TRADING_ALLOWED"])
        self.assertFalse(payload["project_stopped"])
        g1, g2, g3 = payload["G1"], payload["G2"], payload["G3"]
        if g1 == "PASS" and g2 == "PASS" and g3 == "PASS":
            self.assertEqual(payload["AUTHORIZED_NEXT_PHASE"], "EXECUTABLE_COST_AWARE_VALIDATION")
        else:
            self.assertEqual(payload["AUTHORIZED_NEXT_PHASE"], "TARGETED_EVIDENCE_COLLECTION")
        self.assertNotEqual(payload["AUTHORIZED_NEXT_PHASE"], "LIVE_TRADING")
        self.assertGreaterEqual(len(payload["INFORMATION_VALUE_RANKING"]), 3)
        self.assertTrue((root / OPERATOR_MD).is_file())
        op = (root / OPERATOR_MD).read_text(encoding="utf-8")
        self.assertIn("password", op.lower())
        self.assertIn("ECN", op)
        self.assertIn("redacted", op.lower())

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE60_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase60_unified_evidence_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["phase40_scan_rerun"])
        self.assertIn("TARGETED_EVIDENCE_COLLECTION", (root / PHASE60_MD).read_text(encoding="utf-8"))
        closure = (root / PHASE57_60_MD).read_text(encoding="utf-8")
        self.assertIn("OPERATOR_EVIDENCE_REQUEST", closure)
        self.assertIn("DO_NOT_DO_YET", closure)
        self.assertFalse(payload["prior_sources"]["mutated"])


if __name__ == "__main__":
    unittest.main()
