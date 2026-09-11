"""Phase 118 tick forensic validation tests."""

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
    asof_tick_index,
    derive_spread,
    file_sha256,
    validate_tick_frame,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import OUTLIER_TS
from tradingbot.backtest.phase118_tick_forensic_validation import (
    EXPECTED_RAW_SHA256,
    PHASE,
    PHASE40_JSON,
    PHASE40_TS,
    PHASE118_JSON,
    PHASE118_MD,
    discover_raw_exports,
    run_phase118_collection,
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
    art = root / PHASE118_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if (
            payload.get("phase") == PHASE
            and payload.get("RAW_FILE_PRESENT") is True
            and payload.get("MT5_USED") is False
            and payload.get("RAW_FILE_SHA256") == EXPECTED_RAW_SHA256
        ):
            return
    run_phase118_collection(root)


class TestPhase118Helpers(unittest.TestCase):
    def test_identity_gate(self) -> None:
        self.assertTrue(verify_xauusd_i(symbol="XAUUSD_i"))
        self.assertTrue(verify_xauusd_i(path="XAUUSD_i_202607230101_202609072009.csv"))
        self.assertFalse(verify_xauusd_i(symbol="XAUUSD"))
        self.assertFalse(verify_xauusd_i(symbol="GOLD"))
        self.assertFalse(verify_xauusd_i(symbol="GOLDUSD"))

    def test_raw_present_and_hash(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raws = discover_raw_exports(root)
        self.assertTrue(raws)
        # Drop zone may contain later operator exports; Phase118 raw must remain unchanged.
        p118 = next((p for p in raws if p.name == "XAUUSD_i_202607230101_202609072009.csv"), None)
        self.assertIsNotNone(p118)
        self.assertEqual(file_sha256(p118), EXPECTED_RAW_SHA256)
        payload = json.loads((root / PHASE118_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["RAW_FILE_SHA256"], EXPECTED_RAW_SHA256)
        self.assertTrue(payload["RAW_FILE_PRESENT"])
        self.assertGreater(payload["RAW_FILE_ROWS"], 1_000_000)

    def test_window_and_outlier_not_full(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE118_JSON).read_text(encoding="utf-8"))
        self.assertEqual(ACQ_START_ISO, "2023-02-26T15:40:00Z")
        self.assertEqual(ACQ_END_ISO, "2026-09-07T20:10:00Z")
        self.assertEqual(OUTLIER_TS, "2026-01-21T15:40:00Z")
        self.assertFalse(payload["full_horizon_covered"])
        self.assertEqual(payload["HISTORY_RANGE_STATUS"], "PARTIAL")
        self.assertFalse(payload["OUTLIER_31_84R_COVERAGE"])
        self.assertEqual(payload["OUTLIER_31_84R_CHRONOLOGY_STATUS"], "DATA_INSUFFICIENT")
        self.assertTrue(str(payload["ACTUAL_FIRST_TICK"]).startswith("2026-07-23"))
        self.assertTrue(str(payload["ACTUAL_LAST_TICK"]).startswith("2026-09-07"))

    def test_bid_ask_spread_and_no_future(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-08-01T12:00:00Z", "2026-08-01T12:00:00.100000Z"],
                    utc=True,
                    format="ISO8601",
                ),
                "bid": [2400.0, 2400.1],
                "ask": [2400.2, 2400.3],
            }
        )
        self.assertEqual(validate_tick_frame(df)["invalid_rows"], 0)
        self.assertAlmostEqual(derive_spread(2400.0, 2400.2), 0.2)
        ts_ns = df["timestamp_utc"].to_numpy(dtype="datetime64[ns]").astype("int64")
        state = int(pd.Timestamp("2026-08-01T12:00:00.050000Z").value)
        i = asof_tick_index(ts_ns, state)
        self.assertEqual(i, 0)
        self.assertLessEqual(int(ts_ns[i]), state)

    def test_artifact_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE118_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["DATA_ACQUIRED"])
        self.assertFalse(payload["MT5_USED"])
        self.assertFalse(payload["ENV_ACCESSED"])
        self.assertFalse(payload["PRODUCTION_CHANGED"])
        self.assertFalse(payload["EXIT_DESIGN_SPEC_IMPLEMENTED"])
        self.assertEqual(payload["SOURCE_IDENTITY_STATUS"], "VERIFIED")
        self.assertEqual(payload["n_events"], 419)
        self.assertEqual(
            payload["AMBIGUOUS_394_RESOLVED"] + payload["AMBIGUOUS_394_REMAINING"],
            394,
        )


class TestPhase118FrozenAndDocs(unittest.TestCase):
    def test_frozen_tape(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE118_JSON).read_text(encoding="utf-8"))
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        self.assertEqual(file_sha256(root / PHASE40_SETUPS_JSONL), EXPECTED_JSONL_SHA256)
        self.assertEqual(payload["FROZEN_PHASE40_TIMESTAMP"], PHASE40_TS)
        self.assertEqual(payload["FROZEN_PHASE40_FINGERPRINT"], FROZEN)
        self.assertEqual(payload["FROZEN_PHASE40_SHA256"], EXPECTED_JSONL_SHA256)
        self.assertFalse(payload["frozen_integrity"]["repaired"])

    def test_docs_ledger_ku(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn("PHASE118_STATUS", (root / PHASE118_MD).read_text(encoding="utf-8"))
        self.assertIn("H118-01", (root / LEDGER_MD).read_text(encoding="utf-8"))
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 118 started | **YES** |", ku)
        self.assertIn("| Phase 119 started | **YES** |", ku)
        self.assertIn("| Phase 120 started | **YES** |", ku)
        self.assertIn("| Phase 121 started | **YES** |", ku)
        self.assertIn("| Phase 122 started | **YES** |", ku)
        self.assertIn("| Phase 123 started | **YES** |", ku)
        self.assertIn("| Phase 124 started | **NO** |", ku)
        src = (root / "tradingbot/backtest/phase118_tick_forensic_validation.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()