"""Phase 123 engineering decision review tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE40_SETUPS_JSONL
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    EXPECTED_JSONL_SHA256,
    file_sha256,
)
from tradingbot.backtest.phase123_engineering_decision_review import (
    CANONICAL_RESEARCH_UNIT,
    EXIT_ACTION,
    ML_READINESS,
    PHASE,
    PHASE40_JSON,
    PHASE40_TS,
    PHASE123_JSON,
    PHASE123_LOG,
    PHASE123_MD,
    PRIMARY_RECOMMENDATION,
    TAIL_POLICY,
    run_phase123_collection,
)

FORBIDDEN = (
    "from tradingbot.config.live",
    "run_phase40_collection(",
    "symbol_select(",
    "mt5.initialize",
    "copy_ticks_range(",
)
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE123_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if (
            payload.get("phase") == PHASE
            and payload.get("PHASE123_STATUS") == "PASS"
            and payload.get("MT5_USED") is False
            and payload.get("NEW_TICK_EXPORT_REQUIRED") is False
            and payload.get("PRIMARY_RECOMMENDATION") == PRIMARY_RECOMMENDATION
        ):
            return
    run_phase123_collection(root)


class TestPhase123Decision(unittest.TestCase):
    def test_core_decision(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE123_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["PHASE123_STATUS"], "PASS")
        self.assertEqual(payload["DECISION_STATUS"], "DECIDED")
        self.assertEqual(payload["PRIMARY_RECOMMENDATION"], PRIMARY_RECOMMENDATION)
        self.assertEqual(payload["EXIT_ACTION"], EXIT_ACTION)
        self.assertEqual(payload["TAIL_POLICY"], TAIL_POLICY)
        self.assertEqual(payload["ML_READINESS"], ML_READINESS)
        self.assertEqual(payload["CANONICAL_RESEARCH_UNIT"], CANONICAL_RESEARCH_UNIT)
        self.assertFalse(payload["PRODUCTION_CHANGE_ALLOWED"])
        self.assertFalse(payload["NEW_TICK_EXPORT_REQUIRED"])
        self.assertFalse(payload["NEW_TICK_DATA_REQUESTED"])
        self.assertTrue(payload["PHASE124_READY"])
        self.assertFalse(payload["phase124_started"])
        self.assertGreaterEqual(len(payload["DECISION_MATRIX"]), 7)
        self.assertGreaterEqual(len(payload["NEXT_RESEARCH_PROGRAM"]), 3)
        self.assertLessEqual(len(payload["NEXT_RESEARCH_PROGRAM"]), 5)
        self.assertTrue((root / PHASE123_LOG).is_file())
        self.assertIn("FREEZE_CURRENT_SYSTEM", (root / PHASE123_MD).read_text(encoding="utf-8"))

    def test_safety_and_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE123_JSON).read_text(encoding="utf-8"))
        for k in (
            "MT5_USED", "LIVE_TRADING", "ORDERS_PLACED", "ENV_ACCESSED", "PRODUCTION_CHANGED",
            "RISK_GATE_CHANGED", "TRADING_KERNEL_CHANGED", "EXECUTION_CHANGED", "STRATEGY_CHANGED",
            "CALIBRATION_CHANGED", "SIZING_CHANGED", "SLTP_CHANGED", "ML_ACTIVATED",
            "OPTIMIZATION_USED", "EXIT_DESIGN_SPEC_IMPLEMENTED", "NEW_TICK_DATA_REQUESTED",
        ):
            self.assertFalse(payload[k], msg=k)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        self.assertEqual(file_sha256(root / PHASE40_SETUPS_JSONL), EXPECTED_JSONL_SHA256)
        self.assertEqual(payload["FROZEN_PHASE40_SHA256"], EXPECTED_JSONL_SHA256)

    def test_docs_and_hygiene(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn("H123-01", (root / LEDGER_MD).read_text(encoding="utf-8"))
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 123 started | **YES** |", ku)
        self.assertIn("| Phase 124 started | **NO** |", ku)
        src = (root / "tradingbot/backtest/phase123_engineering_decision_review.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertNotIn("mt5.initialize", src)


if __name__ == "__main__":
    unittest.main()