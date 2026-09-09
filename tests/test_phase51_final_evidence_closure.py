"""Phase 51 final evidence-closure tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.optimization_gate import (
    not_proven_symbol_blocks_ev_eq,
    unknown_commission_blocks_executable,
)
from tradingbot.backtest.phase44_executable_backtest_readiness import evaluate_executable_readiness
from tradingbot.backtest.phase51_final_evidence_closure import (
    FROZEN_TAPE_FINGERPRINT,
    PHASE,
    PHASE40_JSON,
    PHASE51_JSON,
    PHASE51_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase51_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE51_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("commission", {}).get("VERIFIED_SCHEDULE") is False:
            return
    run_phase51_collection(root)


class TestPhase51(unittest.TestCase):
    def test_unknown_commission_blocks_executable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE51_JSON).read_text(encoding="utf-8"))
        self.assertTrue(
            unknown_commission_blocks_executable(
                payload["commission"]["status"],
                payload["commission"]["VERIFIED_SCHEDULE"],
            )
        )
        gate = evaluate_executable_readiness(
            {
                "commission": {"evidence_status": "UNKNOWN"},
                "symbol_mapping": {"evidence_status": "NOT_PROVEN"},
                "spread": {"evidence_status": "PARTIAL"},
                "fill_logic": {"evidence_status": "UNKNOWN"},
            }
        )
        self.assertFalse(gate["EXECUTABLE_READY"])

    def test_not_proven_symbol_blocks_ev_eq(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE51_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["symbol"]["EV_EQ_01"], "NOT_PROVEN")
        self.assertTrue(not_proven_symbol_blocks_ev_eq(payload["symbol"]["EV_EQ_01"]))
        self.assertFalse(payload["symbol"]["inferred_from_name_overlap"])

    def test_no_false_closure_and_frozen_intact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE51_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["blockers_closed"], [])
        self.assertGreaterEqual(len(payload["blockers_remaining"]), 6)
        self.assertFalse(payload["commission"]["zero_converted_to_schedule"])
        self.assertEqual(payload["request_fill"]["pairs"], 0)
        self.assertFalse(payload["request_fill"]["synthetic_pairs_created"])
        self.assertFalse(payload["env_accessed"])
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN_TAPE_FINGERPRINT)
        self.assertFalse(payload["phase40_scan_rerun"])

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE51_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        src = (root / "tradingbot/backtest/phase51_final_evidence_closure.py").read_text(encoding="utf-8")
        tel = (root / "tradingbot/backtest/request_fill_telemetry.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
            self.assertNotIn(token, tel)
        self.assertNotIn("def place_order", tel)
        self.assertIn("VERIFIED_SCHEDULE", (root / PHASE51_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
