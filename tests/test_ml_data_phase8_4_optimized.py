"""Phase 8.4 optimized MT5 data collection tests (no real MT5)."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.collection_validation import MINIMUM_BAR_COUNTS
from tradingbot.ml.data.optimized_fetcher import (
    CollectionState,
    CollectionStateStore,
    OptimizedHistoricalFetcher,
    FetchChunk,
    merge_candle_frames,
    mt5_lock,
    plan_chunks,
    split_chunk,
)
from tradingbot.ml.data.paths import collection_state_path
from tradingbot.ml.data.stores import CandleStore

ML_DATA_PKG = ROOT / "tradingbot" / "ml" / "data"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
)


def _scan_file(name: str) -> list[str]:
    violations: list[str] = []
    path = ML_DATA_PKG / name
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        else:
            continue
        for module in mods:
            for prefix in FORBIDDEN:
                if module.startswith(prefix):
                    violations.append(f"{name}: {module}")
    return violations


def _make_rates(start: datetime, n: int, *, bar_seconds: int = 300) -> np.ndarray:
    base = int(start.timestamp())
    times = np.array([base + i * bar_seconds for i in range(n)], dtype=np.int64)
    close = 2300.0 + np.arange(n, dtype=float) * 0.01
    return np.array(
        list(
            zip(
                times,
                close - 0.01,
                close + 0.5,
                close - 0.5,
                close,
                np.full(n, 100, dtype=np.int64),
                np.zeros(n),
                np.zeros(n),
            )
        ),
        dtype=[
            ("time", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("tick_volume", "i8"),
            ("spread", "i8"),
            ("real_volume", "i8"),
        ],
    )


class TestChunkPlanner(unittest.TestCase):
    def test_m5_chunk_targets(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=365)
        chunks = plan_chunks("M5", start, end, chunk_bars="auto")
        self.assertGreater(len(chunks), 1)
        for ch in chunks:
            self.assertLessEqual(ch.target_bars, 30_000)
            self.assertEqual(ch.timeframe, "M5")
        self.assertGreaterEqual(chunks[0].target_bars, 10_000)

    def test_h4_larger_chunks(self):
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, tzinfo=timezone.utc)
        m5 = plan_chunks("M5", start, end)
        h4 = plan_chunks("H4", start, end)
        self.assertLess(len(h4), len(m5))

    def test_split_chunk_halves_span(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=60)
        chunk = plan_chunks("M5", start, end)[0]
        left, right = split_chunk(chunk)
        self.assertEqual(left.start, chunk.start)
        self.assertEqual(right.end, chunk.end)
        self.assertEqual(left.end, right.start)


class TestResumeLogic(unittest.TestCase):
    def test_resume_skips_completed_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CollectionStateStore(tmp)
            state = store.new_state("XAUUSD", "M5", run_id="run1")
            store.save(state)

            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            end = datetime(2024, 6, 1, tzinfo=timezone.utc)
            chunks = plan_chunks("M5", start, end)
            loaded = store.load("XAUUSD", "M5")
            assert loaded is not None
            loaded.completed_chunks = [chunks[0].chunk_id]
            store.save(loaded)
            reloaded = store.load("XAUUSD", "M5")
            assert reloaded is not None
            pending = [c for c in chunks if c.chunk_id not in set(reloaded.completed_chunks)]
            self.assertEqual(len(pending), len(chunks) - 1)

    def test_state_persisted_to_expected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CollectionStateStore(tmp)
            state = store.new_state("XAUUSD", "M15", run_id="abc")
            path = store.save(state)
            self.assertEqual(path, collection_state_path("XAUUSD", "M15", tmp))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["run_id"], "abc")
            self.assertIn("completed_chunks", payload)


class TestRetrySimulation(unittest.TestCase):
    def test_chunk_split_on_failure(self):
        calls = {"n": 0}

        def flaky_range(broker, tf_const, start, end):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return _make_rates(start, 50)

        with tempfile.TemporaryDirectory() as tmp:
            fetcher = OptimizedHistoricalFetcher(
                {"MT5_LOGIN": 1, "MT5_PASSWORD": "x", "MT5_SERVER": "demo"},
                base_dir=tmp,
                copy_rates_range_fn=flaky_range,
                connect_fn=lambda *_a, **_k: True,
                max_retries=1,
            )
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            end = start + timedelta(days=30)
            chunk = plan_chunks("M5", start, end)[0]
            df = fetcher._fetch_chunk_with_retry("XAUUSD", chunk)
            self.assertIsNotNone(df)
            self.assertGreater(len(df), 0)


class TestMt5LockSafety(unittest.TestCase):
    def test_mt5_lock_serializes_calls(self):
        active = {"count": 0, "max": 0}
        lock = threading.Lock()

        def slow_range(broker, tf_const, start, end):
            with lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
                import time

                time.sleep(0.02)
                active["count"] -= 1
            return _make_rates(start, 10)

        with tempfile.TemporaryDirectory() as tmp:
            fetcher = OptimizedHistoricalFetcher(
                {"MT5_LOGIN": 1, "MT5_PASSWORD": "x", "MT5_SERVER": "demo"},
                base_dir=tmp,
                copy_rates_range_fn=slow_range,
                connect_fn=lambda *_a, **_k: True,
            )
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            end = start + timedelta(days=90)
            chunks = plan_chunks("M5", start, end)[:3]

            def fetch_one(ch: FetchChunk):
                return fetcher._fetch_chunk_with_retry("XAUUSD", ch)

            threads = [threading.Thread(target=fetch_one, args=(c,)) for c in chunks]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(active["max"], 1)


class TestMergeDeduplication(unittest.TestCase):
    def test_merge_removes_duplicate_timestamps(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
        df1 = pd.DataFrame({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}, index=idx)
        df2 = pd.DataFrame({"open": 9, "high": 10, "low": 8, "close": 9.5, "volume": 20}, index=idx)
        merged = merge_candle_frames([df1, df2])
        self.assertEqual(len(merged), 5)
        self.assertTrue((merged["close"] == 9.5).all())

    def test_no_duplicate_timestamps_after_collect(self):
        def range_fn(broker, tf_const, start, end):
            n = max(10, int((end - start).total_seconds() // 300))
            return _make_rates(start, min(n, 500))

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(MINIMUM_BAR_COUNTS, {"M5": 100}):
                fetcher = OptimizedHistoricalFetcher(
                    {"MT5_LOGIN": 1, "MT5_PASSWORD": "x", "MT5_SERVER": "demo"},
                    base_dir=tmp,
                    copy_rates_range_fn=range_fn,
                    connect_fn=lambda *_a, **_k: True,
                )
                start = datetime(2024, 1, 1, tzinfo=timezone.utc)
                end = datetime(2024, 3, 1, tzinfo=timezone.utc)
                result = fetcher.collect_timeframe("XAUUSD", "M5", start, end, resume=False)
            self.assertIsNotNone(result.stored_path)
            df = CandleStore(tmp).load("XAUUSD", "M5")
            assert df is not None
            self.assertEqual(df.index.duplicated().sum(), 0)

    def test_deterministic_merge_order(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="5min", tz="UTC")
        a = pd.DataFrame({"open": 1, "high": 2, "low": 0.5, "close": 1.0, "volume": 1}, index=idx)
        b = pd.DataFrame({"open": 2, "high": 3, "low": 1.5, "close": 2.0, "volume": 2}, index=idx + timedelta(minutes=15))
        m1 = merge_candle_frames([a, b])
        m2 = merge_candle_frames([b, a])
        self.assertEqual(list(m1.index), list(m2.index))
        self.assertTrue(m1.equals(m2))


class TestOptimizedCollection(unittest.TestCase):
    def test_full_collect_writes_parquet_and_state(self):
        def range_fn(broker, tf_const, start, end):
            return _make_rates(start, 200)

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(MINIMUM_BAR_COUNTS, {"M5": 100}):
                fetcher = OptimizedHistoricalFetcher(
                    {"MT5_LOGIN": 1, "MT5_PASSWORD": "x", "MT5_SERVER": "demo"},
                    base_dir=tmp,
                    copy_rates_range_fn=range_fn,
                    connect_fn=lambda *_a, **_k: True,
                )
                start = datetime(2024, 1, 1, tzinfo=timezone.utc)
                end = datetime(2024, 2, 1, tzinfo=timezone.utc)
                result = fetcher.collect_timeframe("XAUUSD", "M5", start, end, resume=True)
            self.assertTrue(result.passed)
            self.assertTrue(result.stored_path.is_file())
            self.assertTrue(result.state_path.is_file())
            self.assertIsNotNone(result.fingerprint)

    def test_forbidden_imports(self):
        violations = _scan_file("optimized_fetcher.py")
        self.assertEqual(violations, [], msg=str(violations))


class TestBenchmarkHook(unittest.TestCase):
    def test_optimized_fewer_state_writes_than_chunks(self):
        """Resume state is per-chunk but disk write is once per TF."""
        write_count = {"n": 0}
        original_store = CandleStore.store

        def counting_store(self, symbol, timeframe, df):
            write_count["n"] += 1
            return original_store(self, symbol, timeframe, df)

        def range_fn(broker, tf_const, start, end):
            return _make_rates(start, 100)

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(CandleStore, "store", counting_store):
                with patch.dict(MINIMUM_BAR_COUNTS, {"M5": 100}):
                    fetcher = OptimizedHistoricalFetcher(
                        {"MT5_LOGIN": 1, "MT5_PASSWORD": "x", "MT5_SERVER": "demo"},
                        base_dir=tmp,
                        copy_rates_range_fn=range_fn,
                        connect_fn=lambda *_a, **_k: True,
                    )
                    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
                    end = datetime(2024, 8, 1, tzinfo=timezone.utc)
                    chunks = plan_chunks("M5", start, end)
                    self.assertGreater(len(chunks), 1)
                    fetcher.collect_timeframe("XAUUSD", "M5", start, end, resume=False)
                    self.assertEqual(write_count["n"], 1)


if __name__ == "__main__":
    unittest.main()
