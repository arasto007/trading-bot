"""Phase 117 operator source resolution tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE40_SETUPS_JSONL
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    EXPECTED_JSONL_SHA256,
    derive_spread,
    file_sha256,
    validate_tick_frame,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import OUTLIER_TS
from tradingbot.backtest.phase117_operator_source_resolution import (
    PHASE,
    PHASE40_JSON,
    PHASE40_TS,
    PHASE117_JSON,
    PHASE117_MD,
    RAW_DROP_REL,
    classify_statuses,
    operator_procedure,
    run_phase117_collection,
    validate_raw_export,
)

FORBIDDEN = (
    "from tradingbot.config.live",
    "run_phase40_collection(",
    "symbol_select(",
    "mt5.initialize",
)
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE117_JSON
    drop = root / RAW_DROP_REL
    raw_files = []
    if drop.is_dir():
        raw_files = [
            p
            for p in drop.iterdir()
            if p.is_file() and p.suffix.lower() in {".csv", ".tsv", ".txt", ".parquet", ".zip"}
        ]
    need = True
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        phase_ok = payload.get("phase") == PHASE
        bad_acquired = payload.get("DATA_ACQUIRED") is True and not raw_files
        if phase_ok and not bad_acquired:
            need = False
    if need:
        run_phase117_collection(root)


class TestPhase117Helpers(unittest.TestCase):
    def test_identity_accept_reject(self) -> None:
        self.assertTrue(verify_xauusd_i(symbol="XAUUSD_i"))
        self.assertTrue(verify_xauusd_i(path="XAUUSD_i_ticks_export.csv"))
        self.assertFalse(verify_xauusd_i(symbol="XAUUSD"))
        self.assertFalse(verify_xauusd_i(symbol="GOLD"))
        self.assertFalse(verify_xauusd_i(symbol="GOLDUSD"))

    def test_requested_date_range_and_outlier(self) -> None:
        proc = operator_procedure()
        self.assertEqual(proc["requested_start"], ACQ_START_ISO)
        self.assertEqual(proc["requested_end"], ACQ_END_ISO)
        self.assertEqual(ACQ_START_ISO, "2023-02-26T15:40:00Z")
        self.assertEqual(ACQ_END_ISO, "2026-09-07T20:10:00Z")
        self.assertEqual(OUTLIER_TS, "2026-01-21T15:40:00Z")
        self.assertEqual(proc["outlier_must_include"], OUTLIER_TS)
        self.assertTrue(proc["requested_start"] <= OUTLIER_TS <= proc["requested_end"])
        self.assertFalse(proc["executed_by_this_phase"])
        self.assertEqual(proc["path"][3], "XAUUSD_i")
        self.assertTrue(proc["symbol_gate"]["stop_if_unavailable"])
        self.assertIn("XAUUSD", proc["symbol_gate"]["reject"])

    def test_utc_bid_ask_spread_duplicates_synthetic(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-01-21T15:40:00Z", "2026-01-21T15:40:00.100000Z"],
                    utc=True,
                    format="ISO8601",
                ),
                "bid": [2400.0, 2400.1],
                "ask": [2400.2, 2400.3],
            }
        )
        val = validate_tick_frame(df)
        self.assertEqual(val["invalid_rows"], 0)
        self.assertAlmostEqual(derive_spread(2400.0, 2400.2), 0.2, places=6)
        dup = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-01-21T15:40:00Z", "2026-01-21T15:40:00Z"],
                    utc=True,
                    format="ISO8601",
                ),
                "bid": [1.0, 1.0],
                "ask": [1.1, 1.1],
            }
        )
        self.assertGreater(validate_tick_frame(dup)["duplicate_timestamps"], 0)

    def test_classify_statuses_no_raw(self) -> None:
        st = classify_statuses(raw_present=False)
        self.assertEqual(st["ACQUISITION_STATUS"], "OPERATOR_ACTION_REQUIRED")
        self.assertEqual(st["EXPORT_STATUS"], "MISSING")
        self.assertEqual(st["RAW_INTEGRITY_STATUS"], "MISSING")
        self.assertEqual(st["SOURCE_IDENTITY_STATUS"], "UNKNOWN")
        self.assertEqual(st["HISTORY_RANGE_STATUS"], "UNKNOWN")

    def test_no_future_leakage_validate_raw_export(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-01-21T15:40:00Z", "2026-01-21T15:40:01Z"],
                    utc=True,
                    format="ISO8601",
                ),
                "bid": [2400.0, 2400.1],
                "ask": [2400.2, 2400.3],
            }
        )
        ok = validate_raw_export(
            df,
            path="XAUUSD_i_ticks.csv",
            symbol="XAUUSD_i",
            asof_state_utc="2026-01-21T15:40:01Z",
        )
        self.assertTrue(ok["no_future_leakage"])
        self.assertEqual(ok["future_leakage_vs_asof"], 0)
        leak = validate_raw_export(
            df,
            path="XAUUSD_i_ticks.csv",
            symbol="XAUUSD_i",
            asof_state_utc="2026-01-21T15:39:59Z",
        )
        self.assertFalse(leak["no_future_leakage"])
        self.assertGreater(leak["future_leakage_vs_asof"], 0)


class TestPhase117Collection(unittest.TestCase):
    def test_frozen_tape_integrity(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE117_JSON).read_text(encoding="utf-8"))
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        self.assertEqual(file_sha256(root / PHASE40_SETUPS_JSONL), EXPECTED_JSONL_SHA256)
        self.assertEqual(payload["FROZEN_PHASE40_TIMESTAMP"], PHASE40_TS)
        self.assertEqual(payload["FROZEN_PHASE40_FINGERPRINT"], FROZEN)
        self.assertEqual(payload["FROZEN_PHASE40_SHA256"], EXPECTED_JSONL_SHA256)
        self.assertFalse(payload["frozen_integrity"]["repaired"])

    def test_artifact_safety_and_no_acquisition(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE117_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["DATA_ACQUIRED"])
        self.assertFalse(payload["MT5_USED"])
        self.assertFalse(payload["ENV_ACCESSED"])
        self.assertEqual(payload["ACQUISITION_STATUS"], "OPERATOR_ACTION_REQUIRED")
        self.assertEqual(payload["AMBIGUOUS_394_REMAINING"], 391)
        self.assertFalse(payload["OUTLIER_31_84R_COVERAGE"])
        self.assertEqual(payload["OUTLIER_31_84R_CHRONOLOGY_STATUS"], "DATA_INSUFFICIENT")
        self.assertEqual(payload["TICK_EVENT_COVERAGE"], "N/A_NO_RAW_EXPORT")
        self.assertFalse(payload["EXIT_DESIGN_SPEC_IMPLEMENTED"])
        self.assertFalse(payload["operator_procedure"]["executed_by_this_phase"])

    def test_docs_ledger_and_ku(self) -> None:
        root = Path(__file__).resolve().parents[1]
        md = (root / PHASE117_MD).read_text(encoding="utf-8")
        self.assertIn("PHASE117_STATUS", md)
        ledger = (root / LEDGER_MD).read_text(encoding="utf-8")
        self.assertIn("H117-01", ledger)
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 117 started | **YES** |", ku)
        self.assertIn("| Phase 118 started | **YES** |", ku)
        self.assertIn("| Phase 119 started | **YES** |", ku)
        self.assertIn("| Phase 120 started | **YES** |", ku)
        self.assertIn("| Phase 121 started | **YES** |", ku)
        self.assertIn("| Phase 122 started | **YES** |", ku)
        self.assertIn("| Phase 123 started | **YES** |", ku)
        self.assertIn("| Phase 124 started | **NO** |", ku)
        src = (root / "tradingbot/backtest/phase117_operator_source_resolution.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()