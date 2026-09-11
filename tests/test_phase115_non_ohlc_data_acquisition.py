"""Phase 115 non-OHLC data acquisition and ingestion tests."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE40_SETUPS_JSONL
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    CANONICAL_SYMBOL,
    EXPECTED_JSONL_SHA256,
    PHASE,
    PHASE40_JSON,
    PHASE40_TS,
    PHASE115_JSON,
    PHASE115_MD,
    REQUIRED_ARTIFACT_KEYS,
    asof_tick_index,
    classify_intrabar_order,
    coverage_row,
    derive_spread,
    enforce_utc,
    file_sha256,
    gap_statistics,
    is_weekend_gap,
    last_closed_bar_index,
    quality_class,
    run_phase115_collection,
    validate_ohlc_frame,
    validate_tick_frame,
    verify_xauusd_i,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE115_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("MT5_USED") is False:
            return
    run_phase115_collection(root)


class TestPhase115Helpers(unittest.TestCase):
    def test_symbol_reject_generic_xauusd(self) -> None:
        self.assertFalse(verify_xauusd_i(symbol="XAUUSD"))
        self.assertFalse(verify_xauusd_i(symbol="GOLD"))
        self.assertFalse(verify_xauusd_i(symbol="GOLDUSD"))
        self.assertFalse(verify_xauusd_i(path="data/XAUUSD_1h.parquet"))
        self.assertFalse(verify_xauusd_i(path="data/ml/raw/candles/h4/XAUUSD_h4.parquet"))

    def test_symbol_accept_xauusd_i(self) -> None:
        self.assertTrue(verify_xauusd_i(symbol="XAUUSD_i"))
        self.assertTrue(verify_xauusd_i(path="data/XAUUSD_i_ticks_phase38.parquet"))

    def test_utc_enforcement(self) -> None:
        naive = enforce_utc("2026-08-13 20:20:00")
        self.assertIsNotNone(naive)
        self.assertEqual(str(naive.tzinfo), "UTC")
        aware = enforce_utc("2026-08-13T20:20:00+03:30")
        self.assertIsNotNone(aware)
        self.assertEqual(aware.tzinfo, timezone.utc)
        self.assertEqual(aware.hour, 16)
        self.assertEqual(aware.minute, 50)

    def test_bid_ask_and_spread(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-08-13T20:20:00Z", "2026-08-13T20:20:00.100000Z"], utc=True, format="ISO8601"
                ),
                "bid": [2400.0, 2400.1],
                "ask": [2400.2, 2400.3],
            }
        )
        val = validate_tick_frame(df)
        self.assertEqual(val["invalid_rows"], 0)
        self.assertAlmostEqual(derive_spread(2400.0, 2400.2), 0.2, places=6)
        bad = df.copy()
        bad.loc[0, "ask"] = 2399.0
        self.assertGreater(validate_tick_frame(bad)["ask_lt_bid"], 0)
        zero = df.copy()
        zero.loc[0, "bid"] = 0.0
        self.assertGreater(validate_tick_frame(zero)["nonpositive"], 0)

    def test_duplicates_and_chronology_sort(self) -> None:
        ts = pd.to_datetime(
            ["2026-08-13T20:20:00Z", "2026-08-13T20:20:00Z", "2026-08-13T20:20:01Z"], utc=True, format="ISO8601"
        )
        df = pd.DataFrame({"timestamp_utc": ts, "bid": [1.0, 1.0, 1.1], "ask": [1.1, 1.1, 1.2]})
        self.assertGreater(validate_tick_frame(df)["duplicate_timestamps"], 0)

    def test_weekend_vs_weekday_gaps(self) -> None:
        weekend_start = pd.Timestamp("2026-08-14T21:00:00Z")  # Friday 21:00
        self.assertTrue(is_weekend_gap(weekend_start, pd.Timestamp("2026-08-16T21:00:00Z")))
        tue = pd.Timestamp("2026-08-11T10:00:00Z")
        self.assertFalse(is_weekend_gap(tue, pd.Timestamp("2026-08-11T12:00:00Z")))
        idx = pd.DatetimeIndex(
            [
                "2026-08-13T20:00:00Z",
                "2026-08-13T20:00:01Z",
                "2026-08-14T21:00:00Z",
                "2026-08-16T21:00:00Z",
                "2026-08-17T10:00:00Z",
                "2026-08-17T13:00:00Z",
            ]
        )
        stats = gap_statistics(idx, weekday_threshold=timedelta(minutes=60))
        self.assertGreaterEqual(stats["weekend_gaps"], 1)
        self.assertGreaterEqual(stats["weekday_gaps"], 1)

    def test_asof_no_future_leak(self) -> None:
        ts = np.array(
            [
                pd.Timestamp("2026-08-13T20:20:00Z").value,
                pd.Timestamp("2026-08-13T20:20:05Z").value,
                pd.Timestamp("2026-08-13T20:20:10Z").value,
            ],
            dtype=np.int64,
        )
        state = pd.Timestamp("2026-08-13T20:20:07Z").value
        i = asof_tick_index(ts, state)
        self.assertEqual(i, 1)
        self.assertLessEqual(int(ts[i]), state)
        self.assertEqual(asof_tick_index(ts, pd.Timestamp("2026-08-13T20:19:00Z").value), -1)
        future = pd.Timestamp("2026-08-13T20:20:10Z").value
        self.assertEqual(asof_tick_index(ts, future), 2)

    def test_closed_bar_htf(self) -> None:
        opens = np.array(
            [
                pd.Timestamp("2026-08-13T18:00:00Z").value,
                pd.Timestamp("2026-08-13T19:00:00Z").value,
                pd.Timestamp("2026-08-13T20:00:00Z").value,
            ],
            dtype=np.int64,
        )
        hour = int(timedelta(hours=1).total_seconds() * 1_000_000_000)
        # State at 20:10 — forming 20:00 bar is not closed.
        state = pd.Timestamp("2026-08-13T20:10:00Z").value
        i = last_closed_bar_index(opens, hour, state)
        self.assertEqual(i, 1)
        closed_at = int(opens[i]) + hour
        self.assertLessEqual(closed_at, state)

    def test_intrabar_classes(self) -> None:
        entry = 2400.0
        ts = np.array(
            [
                pd.Timestamp("2026-08-13T20:20:00.001Z").value,
                pd.Timestamp("2026-08-13T20:20:00.002Z").value,
            ],
            dtype=np.int64,
        )
        # BUY: ask rises first, then bid drops.
        fav = classify_intrabar_order(
            "BUY",
            entry,
            ts,
            bid=np.array([2400.0, 2399.0]),
            ask=np.array([2400.5, 2400.5]),
        )
        self.assertEqual(fav["class"], "FAVORABLE_FIRST")
        adv = classify_intrabar_order(
            "BUY",
            entry,
            ts,
            bid=np.array([2399.0, 2399.0]),
            ask=np.array([2400.0, 2400.5]),
        )
        self.assertEqual(adv["class"], "ADVERSE_FIRST")
        same = classify_intrabar_order(
            "BUY",
            entry,
            ts[:1],
            bid=np.array([2399.0]),
            ask=np.array([2401.0]),
        )
        self.assertEqual(same["class"], "SIMULTANEOUS_UNRESOLVED")
        none = classify_intrabar_order("BUY", entry, np.array([], dtype=np.int64), np.array([]), np.array([]))
        self.assertEqual(none["class"], "DATA_INSUFFICIENT")

    def test_incomplete_source_and_matrix(self) -> None:
        self.assertEqual(quality_class(verified=True, n_rows=100, event_cov=3, invalid=False), "PARTIAL")
        self.assertEqual(quality_class(verified=False, n_rows=100, event_cov=40, invalid=False), "INVALID")
        self.assertEqual(quality_class(verified=True, n_rows=0, event_cov=0, invalid=False), "MISSING")
        self.assertEqual(quality_class(verified=True, n_rows=10, event_cov=419, invalid=False), "COMPLETE")
        row = coverage_row(
            "t",
            "tick",
            CANONICAL_SYMBOL,
            "2023-02-26T15:40:00Z",
            "2026-09-07T20:10:00Z",
            None,
            None,
            10,
            3,
            3,
            1,
            0,
            0,
            True,
            True,
            "PARTIAL",
            extra={"bid_available": True, "ask_available": True, "median_gap_ms": 1.0, "max_gap_ms": 2},
        )
        self.assertIn("event_coverage_ratio", row)
        self.assertIn("bid_available", row)
        self.assertLess(row["event_coverage_ratio"], 1.0)

    def test_ohlc_impossible(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(["2026-08-13T20:00:00Z"], utc=True, format="ISO8601"),
                "open": [10.0],
                "high": [9.0],
                "low": [8.0],
                "close": [9.5],
            }
        )
        self.assertGreater(validate_ohlc_frame(df)["invalid_count"], 0)


class TestPhase115Collection(unittest.TestCase):
    def test_ingestion_not_production(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE115_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["MT5_USED"])
        self.assertFalse(payload["LIVE_TRADING"])
        self.assertFalse(payload["ORDERS_PLACED"])
        self.assertFalse(payload["ENV_ACCESSED"])
        self.assertFalse(payload["PRODUCTION_CHANGED"])
        self.assertFalse(payload["RISK_GATE_CHANGED"])
        self.assertFalse(payload["TRADING_KERNEL_CHANGED"])
        self.assertFalse(payload["EXECUTION_CHANGED"])
        self.assertFalse(payload["STRATEGY_CHANGED"])
        self.assertFalse(payload["CALIBRATION_CHANGED"])
        self.assertFalse(payload["SIZING_CHANGED"])
        self.assertFalse(payload["SLTP_CHANGED"])
        self.assertFalse(payload["ML_ACTIVATED"])
        self.assertFalse(payload["OPTIMIZATION_USED"])
        self.assertFalse(payload["EXIT_DESIGN_SPEC_IMPLEMENTED"])
        self.assertEqual(payload["ACQUISITION_STATUS"], "LOCAL_SIDECARS_ONLY")
        self.assertFalse(payload["PHASE116_READY"])
        self.assertEqual(payload["n_events"], 419)
        self.assertLess(payload["TICK_COMPLETE_LIFECYCLE_EVENTS"], 419)
        self.assertEqual(payload["AMBIGUOUS_394_REMAINING"], 394 - payload["AMBIGUOUS_394_RESOLVED"])
        self.assertFalse(payload["OUTLIER_31_84R_TICK_COVERAGE"])
        self.assertEqual(payload["H1_STATUS"], "H1_DATA_MISSING")
        self.assertEqual(payload["NEWS_STATUS"], "NEWS_DATA_MISSING")
        matrix = payload["coverage_matrix"]
        self.assertTrue(any(r.get("timeframe") == "tick" and "median_gap_ms" in r for r in matrix))
        rejected = [s for s in payload["sources"] if s.get("symbol") == "XAUUSD"]
        self.assertTrue(all(s.get("XAUUSD_i_verified") is False for s in rejected))
        ledger = (root / LEDGER_MD).read_text(encoding="utf-8")
        self.assertIn("H115-01", ledger)
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 115 started | **YES** |", ku)
        md = (root / PHASE115_MD).read_text(encoding="utf-8")
        self.assertIn("PHASE115_STATUS", md)
        self.assertIn("XAUUSD_i", md)
        src = (root / "tradingbot/backtest/phase115_non_ohlc_data_acquisition.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertNotIn("mt5.initialize", src)
        self.assertFalse(payload["ticks_synthesized"])
        self.assertFalse(payload["ohlc_used_as_ticks"])

    def test_frozen_phase40_integrity(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE115_JSON).read_text(encoding="utf-8"))
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        sha = file_sha256(root / PHASE40_SETUPS_JSONL)
        self.assertEqual(sha, EXPECTED_JSONL_SHA256)
        self.assertEqual(payload["FROZEN_PHASE40_TIMESTAMP"], PHASE40_TS)
        self.assertEqual(payload["FROZEN_PHASE40_FINGERPRINT"], FROZEN)
        self.assertEqual(payload["FROZEN_PHASE40_SHA256"], EXPECTED_JSONL_SHA256)
        self.assertTrue(payload["frozen_integrity"]["jsonl_byte_identical"])
        self.assertFalse(payload["frozen_integrity"]["repaired"])


if __name__ == "__main__":
    unittest.main()
