"""Phase 1 ML data pipeline tests (no MT5 required)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.mt5_utils import get_mt5_credentials
from tradingbot.adapters.market_cache import ParquetCache
from tradingbot.ml.data.market_event_extractor import extract_market_events
from tradingbot.ml.data.news_calendar import export_news_calendar, iter_known_news_events
from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.roles import (
    CONTEXT_TIMEFRAME,
    DATA_ONLY_TIMEFRAMES,
    ENTRY_TIMEFRAME,
    HIGHER_TIMEFRAME_BIAS,
    TRADING_TIMEFRAMES,
)
from tradingbot.ml.data.schema import MarketEvent, MarketEventType, SpreadRecord, TickRecord
from tradingbot.ml.data.session_utils import classify_session, session_record_at
from tradingbot.ml.data.stores import CandleStore, EventStore, SpreadStore, TickStore


def _synthetic_ohlcv(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    close = 2300 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.2, 2.0, n)
    low = close - rng.uniform(0.2, 2.0, n)
    open_ = close + rng.normal(0, 0.3, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": rng.integers(10, 100, n)},
        index=idx,
    )


class TestArchitectureRoles(unittest.TestCase):
    def test_h4_preserved_as_bias(self):
        self.assertEqual(HIGHER_TIMEFRAME_BIAS, "H4")
        self.assertIn("H4", TRADING_TIMEFRAMES)
        self.assertEqual(CONTEXT_TIMEFRAME, "M15")
        self.assertEqual(ENTRY_TIMEFRAME, "M5")
        self.assertEqual(DATA_ONLY_TIMEFRAMES, ("M1",))


class TestStores(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_candle_roundtrip(self):
        store = CandleStore(self.base)
        df = _synthetic_ohlcv(50)
        path = store.store("XAUUSD", "M1", df)
        loaded = store.load("XAUUSD", "M1")
        self.assertIsNotNone(path)
        self.assertEqual(len(loaded), 50)

    def test_tick_and_spread_stores(self):
        ts = datetime.now(timezone.utc).isoformat()
        tick = TickRecord(ts_utc=ts, symbol="XAUUSD", bid=2300.0, ask=2300.5, spread_pips=0.5)
        spread = SpreadRecord(ts_utc=ts, symbol="XAUUSD", bid=2300.0, ask=2300.5, spread_pips=0.5)
        tpath = TickStore(self.base).append([tick])
        spath = SpreadStore(self.base).append([spread])
        self.assertIsNotNone(tpath)
        self.assertIsNotNone(spath)

    def test_event_store_jsonl(self):
        store = EventStore(self.base)
        ts = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        ev = MarketEvent(
            event_id=MarketEvent.make_id("XAUUSD", "M15", "bos", ts),
            event_type=MarketEventType.BOS.value,
            symbol="XAUUSD",
            timeframe="M15",
            ts_utc=ts.isoformat(),
            direction=1,
            price=2300.0,
        )
        path = store.append([ev])
        rows = store.load_all("XAUUSD", "M15")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_type"], "bos")


class TestMarketEvents(unittest.TestCase):
    def test_extract_events_from_synthetic(self):
        df = _synthetic_ohlcv(300)
        events = extract_market_events(df, "XAUUSD", "M15")
        types = {e.event_type for e in events}
        self.assertTrue(len(events) > 0)
        self.assertTrue(any(t in types for t in ("bos", "choch", "fvg", "order_block", "trading_session")))


class TestSessionAndNews(unittest.TestCase):
    def test_session_classification(self):
        self.assertEqual(classify_session(8).value, "london")
        self.assertEqual(classify_session(13).value, "new_york")
        rec = session_record_at(datetime(2026, 6, 2, 13, 0, tzinfo=timezone.utc), "XAUUSD")
        self.assertEqual(rec.session, "new_york")

    def test_news_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = datetime(2026, 6, 1, tzinfo=timezone.utc)
            end = datetime(2026, 6, 30, tzinfo=timezone.utc)
            rows = iter_known_news_events(start, end)
            self.assertGreater(len(rows), 0)
            path = export_news_calendar(start, end, base_dir=tmp)
            self.assertTrue(path.is_file())


class TestBacktestCacheIsolation(unittest.TestCase):
    """ML candle store must not alter legacy backtest ParquetCache paths."""

    def test_separate_storage_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = ParquetCache(tmp)
            ml = CandleStore(tmp)
            df = _synthetic_ohlcv(30)
            ml.store("XAUUSD", "M1", df)
            legacy_path = legacy.path("XAUUSD", "1m")
            ml_path = Path(tmp) / "ml" / "raw" / "candles" / "m1" / "XAUUSD_m1.parquet"
            self.assertFalse(legacy_path == str(ml_path))
            self.assertTrue(ml_path.is_file())
            self.assertFalse(os.path.exists(legacy_path))


class TestCredentialsEnv(unittest.TestCase):
    def test_env_overrides_config(self):
        os.environ["MT5_LOGIN"] = "12345"
        os.environ["MT5_PASSWORD"] = "secret"
        os.environ["MT5_SERVER"] = "Test-Server"
        try:
            login, password, server = get_mt5_credentials({"MT5_LOGIN": 999, "MT5_PASSWORD": "x"})
            self.assertEqual(login, 12345)
            self.assertEqual(password, "secret")
            self.assertEqual(server, "Test-Server")
        finally:
            os.environ.pop("MT5_LOGIN", None)
            os.environ.pop("MT5_PASSWORD", None)
            os.environ.pop("MT5_SERVER", None)


class TestPipelineWithoutMT5(unittest.TestCase):
    def test_run_full_reports_missing_credentials(self):
        pipe = MLDataPipeline({"MT5_LOGIN": None, "MT5_PASSWORD": "", "MT5_SERVER": ""})
        result = pipe.run_full("XAUUSD")
        self.assertTrue(any("credentials" in e.lower() for e in result.errors))


class TestKernelUntouched(unittest.TestCase):
    def test_import_kernel_risk_execution(self):
        from tradingbot.kernel.trading_kernel import TradingKernel
        from tradingbot.adapters.risk_gate import RiskGate
        from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter

        self.assertTrue(callable(TradingKernel))
        self.assertTrue(callable(RiskGate))
        self.assertTrue(callable(Mt5ExecutionAdapter))


if __name__ == "__main__":
    unittest.main()
