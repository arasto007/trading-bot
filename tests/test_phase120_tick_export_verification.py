"""Phase 120 tick export verification tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE40_SETUPS_JSONL
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    EXPECTED_JSONL_SHA256,
    file_sha256,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import OUTLIER_TS
from tradingbot.backtest.phase118_tick_forensic_validation import (
    EXPECTED_RAW_NAME as PHASE118_RAW_NAME,
    EXPECTED_RAW_SHA256 as PHASE118_SHA256,
)
from tradingbot.backtest.phase120_tick_export_verification import (
    NEW_EXPECTED_NAME,
    NEW_EXPECTED_SHA256,
    PHASE,
    PHASE40_JSON,
    PHASE40_TS,
    PHASE120_JSON,
    PHASE120_MD,
    inventory_raw_files,
    run_phase120_collection,
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
    art = root / PHASE120_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if (
            payload.get("phase") == PHASE
            and payload.get("DATA_ACQUIRED") is True
            and payload.get("MT5_USED") is False
            and payload.get("PHASE118_SHA256_VERIFIED") is True
            and NEW_EXPECTED_NAME in (payload.get("NEW_OPERATOR_FILES") or [])
        ):
            return
    run_phase120_collection(root)


class TestPhase120Helpers(unittest.TestCase):
    def test_identity_and_hashes(self) -> None:
        self.assertTrue(verify_xauusd_i(symbol="XAUUSD_i"))
        self.assertTrue(verify_xauusd_i(path=NEW_EXPECTED_NAME))
        self.assertTrue(verify_xauusd_i(path=PHASE118_RAW_NAME))
        self.assertFalse(verify_xauusd_i(symbol="XAUUSD"))
        self.assertFalse(verify_xauusd_i(symbol="GOLD"))
        root = Path(__file__).resolve().parents[1]
        raw_dir = root / "data/research/non_ohlc/raw/phase117_operator_export"
        self.assertEqual(file_sha256(raw_dir / PHASE118_RAW_NAME), PHASE118_SHA256)
        self.assertEqual(file_sha256(raw_dir / NEW_EXPECTED_NAME), NEW_EXPECTED_SHA256)

    def test_inventory_distinguishes_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        inv = inventory_raw_files(root)
        names = {r["filename"]: r for r in inv}
        self.assertIn(PHASE118_RAW_NAME, names)
        self.assertIn(NEW_EXPECTED_NAME, names)
        self.assertTrue(names[PHASE118_RAW_NAME]["is_phase118"])
        self.assertTrue(names[NEW_EXPECTED_NAME]["is_new_operator_file"])
        self.assertFalse(names[NEW_EXPECTED_NAME]["is_phase118"])


class TestPhase120Collection(unittest.TestCase):
    def test_artifact_core(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE120_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["PHASE120_STATUS"], "PASS")
        self.assertTrue(payload["DATA_ACQUIRED"])
        self.assertTrue(payload["RAW_FILES_UNTOUCHED"])
        self.assertTrue(payload["PHASE118_SHA256_VERIFIED"])
        self.assertEqual(payload["SOURCE_IDENTITY_STATUS"], "VERIFIED")
        self.assertIn(NEW_EXPECTED_NAME, payload["NEW_OPERATOR_FILES"])
        self.assertEqual(payload["NEW_FILE_COUNT"], 1)
        self.assertTrue(str(payload["NEW_EXPORT_FIRST_TICK"]).startswith("2026-05-20"))
        self.assertTrue(str(payload["NEW_EXPORT_LAST_TICK"]).startswith("2026-07-24"))
        self.assertTrue(str(payload["UNION_FIRST_TICK"]).startswith("2026-05-20"))
        self.assertTrue(str(payload["UNION_LAST_TICK"]).startswith("2026-09-07"))
        self.assertGreater(payload["UNION_ROW_COUNT"], 10_000_000)
        self.assertEqual(payload["n_events"], 419)
        self.assertGreaterEqual(payload["TICK_EVENT_COVERAGE"], 12)
        self.assertEqual(
            payload["AMBIGUOUS_394_RESOLVED_TOTAL"] + payload["AMBIGUOUS_394_REMAINING"],
            394,
        )
        self.assertGreaterEqual(payload["AMBIGUOUS_394_RESOLVED_TOTAL"], 12)
        self.assertFalse(payload["OUTLIER_31_84R_TICK_COVERAGE"])
        self.assertEqual(payload["OUTLIER_31_84R_CHRONOLOGY_STATUS"], "DATA_INSUFFICIENT")
        self.assertEqual(OUTLIER_TS, "2026-01-21T15:40:00Z")
        self.assertEqual(payload["FULL_HORIZON_SOURCE_STATUS"], "PARTIAL")
        self.assertEqual(payload["NEXT_ACTION"], "REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT")
        self.assertEqual(payload["REMAINING_MISSING_START"], ACQ_START_ISO)
        self.assertTrue(payload["NEXT_OPERATOR_EXPORT_START"])
        self.assertTrue(payload["NEXT_OPERATOR_EXPORT_END"])
        self.assertEqual(ACQ_END_ISO, "2026-09-07T20:10:00Z")

    def test_safety_and_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE120_JSON).read_text(encoding="utf-8"))
        for k in (
            "MT5_USED",
            "LIVE_TRADING",
            "ORDERS_PLACED",
            "ENV_ACCESSED",
            "PRODUCTION_CHANGED",
            "RISK_GATE_CHANGED",
            "TRADING_KERNEL_CHANGED",
            "EXECUTION_CHANGED",
            "STRATEGY_CHANGED",
            "CALIBRATION_CHANGED",
            "SIZING_CHANGED",
            "SLTP_CHANGED",
            "ML_ACTIVATED",
            "OPTIMIZATION_USED",
            "EXIT_DESIGN_SPEC_IMPLEMENTED",
            "phase121_started",
        ):
            self.assertFalse(payload[k], msg=k)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        self.assertEqual(file_sha256(root / PHASE40_SETUPS_JSONL), EXPECTED_JSONL_SHA256)
        self.assertEqual(payload["FROZEN_PHASE40_TIMESTAMP"], PHASE40_TS)
        self.assertEqual(payload["FROZEN_PHASE40_FINGERPRINT"], FROZEN)
        self.assertEqual(payload["FROZEN_PHASE40_SHA256"], EXPECTED_JSONL_SHA256)

    def test_docs_and_source_hygiene(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn("PHASE120_STATUS", (root / PHASE120_MD).read_text(encoding="utf-8"))
        self.assertIn("H120-01", (root / LEDGER_MD).read_text(encoding="utf-8"))
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 120 started | **YES** |", ku)
        self.assertIn("| Phase 121 started | **YES** |", ku)
        self.assertIn("| Phase 122 started | **YES** |", ku)
        self.assertIn("| Phase 123 started | **YES** |", ku)
        self.assertIn("| Phase 124 started | **NO** |", ku)
        src = (root / "tradingbot/backtest/phase120_tick_export_verification.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()