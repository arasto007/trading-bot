"""Phase 122 tick export verification tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE40_SETUPS_JSONL
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_START_ISO,
    EXPECTED_JSONL_SHA256,
    file_sha256,
    verify_xauusd_i,
)
from tradingbot.backtest.phase118_tick_forensic_validation import (
    EXPECTED_RAW_NAME as PHASE118_RAW_NAME,
    EXPECTED_RAW_SHA256 as PHASE118_SHA256,
)
from tradingbot.backtest.phase120_tick_export_verification import (
    NEW_EXPECTED_NAME as PHASE120_RAW_NAME,
    NEW_EXPECTED_SHA256 as PHASE120_SHA256,
)
from tradingbot.backtest.phase121_tick_export_verification import (
    NEW_EXPECTED_NAME as PHASE121_RAW_NAME,
    NEW_EXPECTED_SHA256 as PHASE121_SHA256,
)
from tradingbot.backtest.phase122_tick_export_verification import (
    NEW_EXPECTED_NAME,
    NEW_EXPECTED_SHA256,
    PHASE,
    PHASE40_JSON,
    PHASE40_TS,
    PHASE122_JSON,
    PHASE122_LOG,
    PHASE122_MD,
    inventory_raw_files,
    run_phase122_collection,
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
    art = root / PHASE122_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if (
            payload.get("phase") == PHASE
            and payload.get("DATA_ACQUIRED") is True
            and payload.get("MT5_USED") is False
            and payload.get("PHASE118_SHA256_VERIFIED") is True
            and payload.get("PHASE120_SHA256_VERIFIED") is True
            and payload.get("PHASE121_SHA256_VERIFIED") is True
            and NEW_EXPECTED_NAME in (payload.get("NEW_OPERATOR_FILES") or [])
        ):
            return
    run_phase122_collection(root)


class TestPhase122Helpers(unittest.TestCase):
    def test_identity_and_prior_hashes(self) -> None:
        self.assertTrue(verify_xauusd_i(path=NEW_EXPECTED_NAME))
        self.assertFalse(verify_xauusd_i(symbol="XAUUSD"))
        root = Path(__file__).resolve().parents[1]
        raw = root / "data/research/non_ohlc/raw/phase117_operator_export"
        self.assertEqual(file_sha256(raw / PHASE118_RAW_NAME), PHASE118_SHA256)
        self.assertEqual(file_sha256(raw / PHASE120_RAW_NAME), PHASE120_SHA256)
        self.assertEqual(file_sha256(raw / PHASE121_RAW_NAME), PHASE121_SHA256)
        self.assertEqual(file_sha256(raw / NEW_EXPECTED_NAME), NEW_EXPECTED_SHA256)

    def test_inventory(self) -> None:
        root = Path(__file__).resolve().parents[1]
        inv = {r["filename"]: r for r in inventory_raw_files(root)}
        self.assertTrue(inv[PHASE121_RAW_NAME]["is_phase121"])
        self.assertTrue(inv[NEW_EXPECTED_NAME]["is_new_operator_file"])


class TestPhase122Collection(unittest.TestCase):
    def test_artifact_core(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE122_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["PHASE122_STATUS"], "PASS")
        self.assertTrue(payload["DATA_ACQUIRED"])
        self.assertTrue(payload["RAW_FILES_UNTOUCHED"])
        self.assertEqual(payload["SOURCE_IDENTITY_STATUS"], "VERIFIED")
        self.assertIn(NEW_EXPECTED_NAME, payload["NEW_OPERATOR_FILES"])
        self.assertTrue(str(payload["ACTUAL_FIRST_TICK"]).startswith("2025-11-03"))
        self.assertTrue(str(payload["ACTUAL_LAST_TICK"]).startswith("2026-01-02"))
        self.assertTrue(str(payload["UNION_FIRST_TICK"]).startswith("2025-11-03"))
        self.assertTrue(str(payload["UNION_LAST_TICK"]).startswith("2026-09-07"))
        self.assertGreaterEqual(payload["TICK_EVENT_COVERAGE"], 61)
        self.assertEqual(
            payload["AMBIGUOUS_394_RESOLVED"] + payload["AMBIGUOUS_394_REMAINING"],
            394,
        )
        self.assertTrue(payload["OUTLIER_31_84R_COVERAGE"])
        self.assertEqual(payload["OUTLIER_31_84R_CHRONOLOGY_STATUS"], "ADVERSE_FIRST")
        self.assertEqual(payload["REMAINING_MISSING_START"], ACQ_START_ISO)
        self.assertEqual(payload["NEXT_ACTION"], "REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT")
        self.assertFalse(payload["PHASE123_READY"])
        self.assertTrue((root / PHASE122_LOG).is_file())

    def test_safety_and_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE122_JSON).read_text(encoding="utf-8"))
        for k in (
            "MT5_USED", "LIVE_TRADING", "ORDERS_PLACED", "ENV_ACCESSED", "PRODUCTION_CHANGED",
            "RISK_GATE_CHANGED", "TRADING_KERNEL_CHANGED", "EXECUTION_CHANGED", "STRATEGY_CHANGED",
            "CALIBRATION_CHANGED", "SIZING_CHANGED", "SLTP_CHANGED", "ML_ACTIVATED",
            "OPTIMIZATION_USED", "EXIT_DESIGN_SPEC_IMPLEMENTED", "phase123_started",
        ):
            self.assertFalse(payload[k], msg=k)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        self.assertEqual(file_sha256(root / PHASE40_SETUPS_JSONL), EXPECTED_JSONL_SHA256)

    def test_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn("PHASE122_STATUS", (root / PHASE122_MD).read_text(encoding="utf-8"))
        self.assertIn("H122-01", (root / LEDGER_MD).read_text(encoding="utf-8"))
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 122 started | **YES** |", ku)
        self.assertIn("| Phase 123 started | **YES** |", ku)
        self.assertIn("| Phase 124 started | **NO** |", ku)
        src = (root / "tradingbot/backtest/phase122_tick_export_verification.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()