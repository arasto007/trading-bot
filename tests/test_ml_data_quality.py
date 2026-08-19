"""Phase 1.1 ML data quality and storage hardening tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.metadata import MetadataStore
from tradingbot.ml.data.paths import (
    candles_dir,
    datasets_root,
    ensure_storage_layout,
    features_dir,
    metadata_root,
    processed_root,
    raw_root,
)
from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.quality.candle_validator import validate_candles
from tradingbot.ml.data.quality.gap_detector import detect_candle_gaps
from tradingbot.ml.data.quality.tick_validator import validate_ticks
from tradingbot.ml.data.schema import EventOutcome, MarketEvent, MarketEventType
from tradingbot.ml.data.stores import CandleStore, EventStore


def _good_ohlcv(n: int = 100, freq: str = "5min") -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    close = 2300 + np.arange(n) * 0.01
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(n) * 10,
        },
        index=idx,
    )


class TestCandleValidation(unittest.TestCase):
    def test_valid_candles_pass(self):
        df = _good_ohlcv()
        report = validate_candles(df, "XAUUSD", "M5")
        self.assertEqual(report.status, "pass")
        self.assertEqual(report.row_count, 100)

    def test_duplicate_timestamps_detected(self):
        df = _good_ohlcv(20)
        dup = pd.concat([df.iloc[:1], df])
        report = validate_candles(dup, "XAUUSD", "M5")
        self.assertEqual(report.status, "fail")
        self.assertGreater(report.duplicate_count, 0)

    def test_invalid_ohlc_detected(self):
        df = _good_ohlcv(20)
        df.iloc[5, df.columns.get_loc("high")] = df.iloc[5]["low"] - 1
        report = validate_candles(df, "XAUUSD", "M5")
        self.assertEqual(report.status, "fail")
        codes = {i.code for i in report.issues}
        self.assertIn("high_lt_low", codes)

    def test_close_out_of_range_detected(self):
        df = _good_ohlcv(20)
        df.iloc[3, df.columns.get_loc("close")] = df.iloc[3]["high"] + 10
        report = validate_candles(df, "XAUUSD", "M5")
        self.assertEqual(report.status, "fail")

    def test_missing_candles_gaps_detected(self):
        df = _good_ohlcv(50, freq="5min")
        # Remove a chunk to create gap
        gap_df = pd.concat([df.iloc[:10], df.iloc[20:]])
        gaps = detect_candle_gaps(gap_df, "M5")
        report = validate_candles(gap_df, "XAUUSD", "M5")
        self.assertGreater(len(gaps), 0)
        self.assertGreater(report.gap_count, 0)
        self.assertGreater(report.missing_bars_estimate, 0)


class TestTickValidation(unittest.TestCase):
    def test_invalid_ticks_detected(self):
        df = pd.DataFrame(
            [
                {"ts_utc": "2026-01-01T12:00:00+00:00", "bid": 0, "ask": 2300, "spread_pips": 1},
                {"ts_utc": "2026-01-01T12:00:01+00:00", "bid": 2300, "ask": 2299, "spread_pips": 1},
                {"ts_utc": "2026-01-01T12:00:01+00:00", "bid": 2300, "ask": 2300.5, "spread_pips": 0.5},
            ]
        )
        report = validate_ticks(df, "XAUUSD")
        codes = {i.code for i in report.issues}
        self.assertIn("invalid_tick_prices", codes)
        self.assertIn("duplicate_ticks", codes)


class TestEventOutcomeSchema(unittest.TestCase):
    def test_outcome_fields_in_serialization(self):
        ts = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        ev = MarketEvent(
            event_id=MarketEvent.make_id("XAUUSD", "M15", "bos", ts),
            event_type=MarketEventType.BOS.value,
            symbol="XAUUSD",
            timeframe="M15",
            ts_utc=ts.isoformat(),
            outcome=EventOutcome(evaluated=False, future_window_bars=None),
        )
        payload = ev.to_dict()
        self.assertIn("outcome", payload)
        self.assertFalse(payload["outcome"]["evaluated"])
        self.assertIsNone(payload["outcome"]["tp_hit"])

    def test_legacy_event_load_without_outcome(self):
        restored = MarketEvent.from_dict(
            {
                "event_id": "x",
                "event_type": "bos",
                "symbol": "XAUUSD",
                "timeframe": "M15",
                "ts_utc": "2026-01-01T12:00:00+00:00",
            }
        )
        self.assertFalse(restored.outcome.evaluated)


class TestStorageSeparation(unittest.TestCase):
    def test_raw_processed_datasets_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ensure_storage_layout(tmp)
            self.assertTrue(raw_root(tmp).is_dir())
            self.assertTrue(processed_root(tmp).is_dir())
            self.assertTrue(datasets_root(tmp).is_dir())
            self.assertTrue(metadata_root(tmp).is_dir())
            self.assertTrue(features_dir(tmp).is_dir())
            self.assertTrue(candles_dir(tmp).is_dir())
            # processed must not be under raw
            self.assertNotEqual(str(features_dir(tmp)).startswith(str(raw_root(tmp))), True)

    def test_candles_stored_under_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CandleStore(tmp)
            df = _good_ohlcv(10, freq="1min")
            path = store.store("XAUUSD", "M1", df)
            self.assertIn("raw", str(path).replace("\\", "/"))
            self.assertIn("candles", str(path).replace("\\", "/"))


class TestMetadata(unittest.TestCase):
    def test_metadata_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = MetadataStore(tmp)
            path = meta.update_candles("XAUUSD", "M5", row_count=1000, broker="Test", validation_status="pass")
            loaded = meta.load("XAUUSD", "M5")
            self.assertEqual(loaded["row_count"], 1000)
            self.assertEqual(loaded["validation_status"], "pass")
            self.assertTrue(path.name.endswith("_metadata.json"))


class TestPipelineReport(unittest.TestCase):
    def test_status_report_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = MLDataPipeline({"MT5_LOGIN": None, "MT5_PASSWORD": "", "MT5_SERVER": ""}, base_dir=tmp)
            store = CandleStore(tmp)
            store.store("XAUUSD", "M5", _good_ohlcv())
            store.store("XAUUSD", "H4", _good_ohlcv(80, freq="4h"))
            report = pipe.build_status_report("XAUUSD")
            self.assertIn("H4", report.candles)
            self.assertIn("M5", report.candles)
            self.assertTrue(report.candles["H4"].available)
            self.assertIn("storage_layout", report.to_dict())
            self.assertIn("validation_reports", report.to_dict())


if __name__ == "__main__":
    unittest.main()
