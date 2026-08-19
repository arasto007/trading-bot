"""Phase 8.0 historical data collection tests (no MT5 required)."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.collection_manifest import (
    CollectionRunManifest,
    build_collection_manifest,
    load_collection_manifest,
    save_collection_manifest,
)
from tradingbot.ml.data.collection_validation import (
    MINIMUM_BAR_COUNTS,
    validate_candle_structure,
    validate_for_storage,
)
from tradingbot.ml.data.historical_fetcher import HistoricalCandleFetcher
from tradingbot.ml.data.metadata import MetadataStore
from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.raw_fingerprint import fingerprint_dataframe_parquet_bytes, fingerprint_parquet
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


def _scan_package(package_dir: Path, filenames: tuple[str, ...] | None = None) -> list[str]:
    violations: list[str] = []
    paths = (
        [package_dir / name for name in filenames]
        if filenames
        else list(package_dir.glob("*.py"))
    )
    for path in paths:
        if not path.is_file():
            continue
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
                        violations.append(f"{path.name}: {module}")
    return violations


def _make_rates(start: datetime, n: int, *, bar_seconds: int = 300) -> np.ndarray:
    base = int(start.timestamp())
    times = np.array([base + i * bar_seconds for i in range(n)], dtype=np.int64)
    close = 2300.0 + np.arange(n, dtype=float) * 0.01
    high = close + 0.5
    low = close - 0.5
    open_ = close - 0.01
    vol = np.full(n, 100, dtype=np.int64)
    return np.array(
        list(
            zip(
                times,
                open_,
                high,
                low,
                close,
                vol,
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


def _synthetic_ohlcv(n: int, *, freq: str = "5min", start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    close = 2300 + np.arange(n) * 0.01
    return pd.DataFrame(
        {
            "open": close - 0.01,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


class TestHistoricalFetcherChunkMerge(unittest.TestCase):
    def test_chunk_merge_deduplicates(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 3, 1, tzinfo=timezone.utc)
        calls: list[tuple[datetime, datetime]] = []

        def fake_range(_broker, _tf, s, e):
            calls.append((s, e))
            n = 500
            return _make_rates(s, n)

        fetcher = HistoricalCandleFetcher(
            {"MT5_LOGIN": 1, "MT5_PASSWORD": "x", "MT5_SERVER": "demo"},
            connect_fn=lambda *_a, **_k: True,
            copy_rates_range_fn=fake_range,
        )
        with patch.dict(MINIMUM_BAR_COUNTS, {"M5": 100}):
            df = fetcher.fetch_chunked("XAUUSD", "M5", start, end, chunk_size_days=30)
        self.assertIsNotNone(df)
        self.assertGreater(len(df), 100)
        self.assertFalse(df.index.duplicated().any())
        self.assertTrue(df.index.is_monotonic_increasing)
        self.assertGreater(len(calls), 1)


class TestDuplicateRemoval(unittest.TestCase):
    def test_duplicate_timestamp_removal(self):
        df = _synthetic_ohlcv(10)
        dup = pd.concat([df, df.iloc[[3, 4]]])
        dup = dup[~dup.index.duplicated(keep="last")].sort_index()
        self.assertEqual(len(dup), len(df))
        result = validate_candle_structure(dup)
        self.assertTrue(result.passed)


class TestIncrementalResume(unittest.TestCase):
    def test_incremental_uses_metadata_last_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = MetadataStore(tmp)
            last = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
            meta.update_candles("XAUUSD", "M5", row_count=100, path="x")
            meta.save(
                "XAUUSD",
                "M5",
                {
                    **meta.load("XAUUSD", "M5"),
                    "last_update_utc": last.isoformat(),
                },
            )
            seen: dict[str, datetime] = {}

            def fake_range(_broker, _tf, s, e):
                seen["start"] = s
                seen["end"] = e
                return _make_rates(s, 20)

            fetcher = HistoricalCandleFetcher(
                {"MT5_LOGIN": 1, "MT5_PASSWORD": "x", "MT5_SERVER": "demo"},
                base_dir=tmp,
                connect_fn=lambda *_a, **_k: True,
                copy_rates_range_fn=fake_range,
            )
            df = fetcher.fetch_incremental("XAUUSD", "M5", default_days=30)
            self.assertIsNotNone(df)
            self.assertEqual(seen["start"], last)


class TestManifestGeneration(unittest.TestCase):
    def test_manifest_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_collection_manifest(
                symbol="XAUUSD",
                timeframes=["M5", "M15"],
                date_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                date_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
                bars_fetched={"M5": 1000},
                validation_status="pass",
                raw_files={"M5": str(Path(tmp) / "raw.parquet")},
                fingerprint={"M5": "abc123"},
                base_dir=tmp,
            )
            path = save_collection_manifest(manifest, base_dir=tmp)
            loaded = load_collection_manifest(manifest.run_id, base_dir=tmp)
            self.assertTrue(path.is_file())
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.symbol, "XAUUSD")
            self.assertIn("M5", loaded.timeframes)


class TestFingerprintReproducibility(unittest.TestCase):
    def test_fingerprint_is_deterministic(self):
        df = _synthetic_ohlcv(50)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candles.parquet"
            df.to_parquet(path)
            h1 = fingerprint_parquet(path)
            h2 = fingerprint_parquet(path)
            self.assertEqual(h1, h2)
            self.assertEqual(h1, fingerprint_dataframe_parquet_bytes(df))


class TestValidationGate(unittest.TestCase):
    def test_rejects_bad_candles(self):
        df = _synthetic_ohlcv(100)
        df.iloc[5, df.columns.get_loc("high")] = df.iloc[5]["low"] - 1
        result = validate_candle_structure(df)
        self.assertFalse(result.passed)

    def test_rejects_below_minimum(self):
        df = _synthetic_ohlcv(100)
        result = validate_for_storage(df, "M5")
        self.assertFalse(result.passed)
        self.assertTrue(any("below_minimum" in i for i in result.issues))


class TestIsolation(unittest.TestCase):
    def test_no_forbidden_imports_in_phase8_modules(self):
        files = (
            "historical_fetcher.py",
            "collection_manifest.py",
            "collection_validation.py",
            "raw_fingerprint.py",
        )
        violations = _scan_package(ML_DATA_PKG, files)
        self.assertEqual(violations, [], msg=str(violations))

    def test_no_trading_kernel_dependency(self):
        violations = _scan_package(ML_DATA_PKG, ("historical_fetcher.py", "pipeline.py"))
        kernel_hits = [v for v in violations if "kernel" in v]
        self.assertEqual(kernel_hits, [])

    def test_no_execution_dependency(self):
        violations = _scan_package(ML_DATA_PKG, ("historical_fetcher.py", "pipeline.py"))
        exec_hits = [v for v in violations if "execution" in v or "mt5_execution" in v]
        self.assertEqual(exec_hits, [])


class TestMockCollectionPipeline(unittest.TestCase):
    def test_collect_historical_with_mock_fetcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = MLDataPipeline(base_dir=tmp)

            def fake_chunked(symbol, tf, start, end, chunk_size_days=30, max_retries=3):
                days = max(1, (end - start).days)
                bars = days * 288 if tf == "M5" else days * 96
                bars = max(bars, MINIMUM_BAR_COUNTS.get(tf, 1000) + 10)
                return _synthetic_ohlcv(bars, freq="5min" if tf == "M5" else "15min")

            with patch.object(HistoricalCandleFetcher, "fetch_chunked", side_effect=fake_chunked):
                with patch(
                    "tradingbot.ml.data.pipeline.credentials_configured",
                    return_value=True,
                ):
                    result = pipe.collect_historical(
                        "XAUUSD",
                        timeframes=["M5"],
                        days=365,
                    )
            self.assertIn("M5", result.stored)
            self.assertIsNotNone(result.manifest_path)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["symbol"], "XAUUSD")
            self.assertIn("M5", manifest["fingerprint"])
            loaded = CandleStore(tmp).load("XAUUSD", "M5")
            self.assertIsNotNone(loaded)
            self.assertGreaterEqual(len(loaded), MINIMUM_BAR_COUNTS["M5"])


if __name__ == "__main__":
    unittest.main()
