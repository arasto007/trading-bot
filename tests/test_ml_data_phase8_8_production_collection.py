"""Phase 8.8 production 5-year historical collection validation tests (offline)."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.historical_collection_report import (
    build_collection_report,
    run_production_5y,
    save_collection_report,
)
from tradingbot.ml.data.historical_quality_validator import (
    PRODUCTION_5Y_DAYS,
    PRODUCTION_MIN_BARS,
    HistoricalQualityValidator,
    ProductionQualityConfig,
    fingerprint_content,
    fingerprint_metadata,
    is_weekend_gap,
    normalize_candles,
    production_date_range,
)
from tradingbot.ml.data.optimized_fetcher import CollectionStateStore
from tradingbot.ml.data.paths import (
    historical_quality_report_path,
    production_5y_collection_report_path,
)
from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.raw_fingerprint import fingerprint_dataframe_parquet_bytes
from tradingbot.ml.data.stores.candle_store import CandleStore

ML_DATA_PKG = ROOT / "tradingbot" / "ml" / "data"
PHASE88_FILES = ("historical_quality_validator.py", "historical_collection_report.py")
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
)
MT5_WRITE_OPS = ("order_send", "order_check", "positions_close", "positions_open")


def _scan_files(filenames: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for name in filenames:
        path = ML_DATA_PKG / name
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            else:
                continue
            for module in mods:
                for prefix in FORBIDDEN:
                    if module.startswith(prefix) or module == prefix:
                        violations.append(f"{name}: {module}")
        for op in MT5_WRITE_OPS:
            if op in text:
                violations.append(f"{name}: {op}")
    return violations


def _test_config() -> ProductionQualityConfig:
    return ProductionQualityConfig(
        min_days=30,
        min_bars={"M5": 200, "M15": 80, "H4": 20},
        days_tolerance=5,
        max_large_gaps=5,
    )


def _make_ohlcv(
    start: datetime,
    n: int,
    *,
    bar_minutes: int,
    seed: int = 0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq=f"{bar_minutes}min", tz="UTC")
    close = 2300.0 + rng.normal(0, 1, n).cumsum() * 0.01
    df = pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "tick_volume": rng.integers(50, 500, n),
        },
        index=ts,
    )
    return df


def _store_aligned_5y_synthetic(tmp: str, *, days: int = 35) -> datetime:
    start = datetime(2021, 1, 4, tzinfo=timezone.utc)
    store = CandleStore(tmp)
    m5_n = int((days * 24 * 60) / 5) + 1
    m15_n = int((days * 24 * 60) / 15) + 1
    h4_n = int((days * 24) / 4) + 1
    store.store("XAUUSD", "M5", _make_ohlcv(start, m5_n, bar_minutes=5))
    store.store("XAUUSD", "M15", _make_ohlcv(start, m15_n, bar_minutes=15))
    store.store("XAUUSD", "H4", _make_ohlcv(start, h4_n, bar_minutes=240))
    return start


class TestFiveYearDateRange(unittest.TestCase):
    def test_production_date_range_1825_days(self):
        end = datetime(2026, 1, 1, tzinfo=timezone.utc)
        start, end_out = production_date_range(end=end, days=PRODUCTION_5Y_DAYS)
        self.assertEqual(end_out, end)
        self.assertEqual((end - start).days, PRODUCTION_5Y_DAYS)

    def test_minimum_bar_constants(self):
        self.assertGreaterEqual(PRODUCTION_MIN_BARS["M5"], 300_000)
        self.assertGreaterEqual(PRODUCTION_MIN_BARS["M15"], 100_000)
        self.assertGreaterEqual(PRODUCTION_MIN_BARS["H4"], 7_000)

    def test_minimum_bar_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            CandleStore(tmp).store("XAUUSD", "M5", _make_ohlcv(start, 50, bar_minutes=5))
            result = HistoricalQualityValidator(
                tmp,
                ProductionQualityConfig(min_days=5, min_bars={"M5": 300_000}),
            ).validate_timeframe("XAUUSD", "M5")
            self.assertEqual(result.status, "FAIL")
            self.assertTrue(any("below_minimum_bars" in i for i in result.issues))


class TestCandleIntegrity(unittest.TestCase):
    def test_duplicate_timestamp_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            df = _make_ohlcv(start, 50, bar_minutes=5)
            df = pd.concat([df, df.iloc[[10]]])
            store = CandleStore(tmp)
            store.store("XAUUSD", "M5", df)
            result = HistoricalQualityValidator(tmp, _test_config()).validate_timeframe("XAUUSD", "M5")
            self.assertGreater(result.duplicates, 0)
            self.assertEqual(result.status, "FAIL")

    def test_ohlc_corruption_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            df = _make_ohlcv(start, 50, bar_minutes=5)
            df.iloc[5, df.columns.get_loc("high")] = 0.0
            store = CandleStore(tmp)
            store.store("XAUUSD", "M5", df)
            result = HistoricalQualityValidator(tmp, _test_config()).validate_timeframe("XAUUSD", "M5")
            self.assertGreater(result.corrupted_candles, 0)
            self.assertEqual(result.status, "FAIL")

    def test_utc_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            df = _make_ohlcv(start, 100, bar_minutes=5)
            norm = normalize_candles(df)
            assert norm is not None
            self.assertIsNotNone(norm.index.tz)
            result = HistoricalQualityValidator(tmp, _test_config()).validate_timeframe(
                "XAUUSD", "M5", df=df
            )
            self.assertTrue(result.utc_valid)


class TestGapDetection(unittest.TestCase):
    def test_missing_candle_gap_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            df = _make_ohlcv(start, 100, bar_minutes=5)
            df = df.drop(df.index[40:60])
            store = CandleStore(tmp)
            store.store("XAUUSD", "M5", df)
            result = HistoricalQualityValidator(tmp, _test_config()).validate_timeframe("XAUUSD", "M5")
            self.assertGreater(result.missing_gaps, 0)

    def test_weekend_gap_not_counted_as_large(self):
        fri = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)
        mon = datetime(2024, 1, 8, 1, 0, tzinfo=timezone.utc)
        self.assertTrue(is_weekend_gap(pd.Timestamp(fri), pd.Timestamp(mon)))


class TestCrossTimeframeAlignment(unittest.TestCase):
    def test_m5_aligns_with_m15_and_h4(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = _store_aligned_5y_synthetic(tmp)
            end = start + timedelta(days=30)
            validator = HistoricalQualityValidator(tmp, _test_config())
            cross = validator.validate_cross_timeframes(
                "XAUUSD",
                {
                    "M5": CandleStore(tmp).load("XAUUSD", "M5"),
                    "M15": CandleStore(tmp).load("XAUUSD", "M15"),
                    "H4": CandleStore(tmp).load("XAUUSD", "H4"),
                },
            )
            self.assertEqual(cross["status"], "PASS")

    def test_misaligned_m15_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            store = CandleStore(tmp)
            store.store("XAUUSD", "M5", _make_ohlcv(start, 200, bar_minutes=5))
            store.store("XAUUSD", "M15", _make_ohlcv(start + timedelta(hours=3), 50, bar_minutes=15))
            store.store("XAUUSD", "H4", _make_ohlcv(start, 20, bar_minutes=240))
            cfg = ProductionQualityConfig(
                min_days=5,
                min_bars={"M5": 100, "M15": 30, "H4": 10},
                max_cross_tf_misaligned_pct=0.0,
            )
            cross = HistoricalQualityValidator(tmp, cfg).validate_cross_timeframes("XAUUSD")
            self.assertEqual(cross["status"], "FAIL")


class TestFingerprints(unittest.TestCase):
    def test_fingerprint_reproducibility(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv(start, 100, bar_minutes=5, seed=99)
        fp1 = fingerprint_content(df)
        fp2 = fingerprint_content(df)
        self.assertEqual(fp1, fp2)
        meta = fingerprint_metadata({"symbol": "XAUUSD", "bars": 100})
        self.assertEqual(len(meta), 64)
        self.assertEqual(fingerprint_dataframe_parquet_bytes(df), fingerprint_dataframe_parquet_bytes(df))


class TestReportGeneration(unittest.TestCase):
    def test_collection_report_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = _store_aligned_5y_synthetic(tmp)
            cfg = _test_config()
            validator = HistoricalQualityValidator(tmp, cfg)
            quality = validator.validate_all(
                "XAUUSD",
                expected_start=start,
                expected_end=start + timedelta(days=35),
            )
            payload = build_collection_report("XAUUSD", quality)
            path = save_collection_report("XAUUSD", payload, tmp)
            self.assertEqual(path, production_5y_collection_report_path("XAUUSD", tmp))
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["symbol"], "XAUUSD")
            self.assertEqual(loaded["period"], "5Y")
            self.assertIn("M5", loaded["timeframes"])


class TestProductionWorkflow(unittest.TestCase):
    def test_validate_only_passes_synthetic_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = _store_aligned_5y_synthetic(tmp)
            pipe = MLDataPipeline(base_dir=tmp)
            result = run_production_5y(
                pipe,
                "XAUUSD",
                days=30,
                validate_only=True,
                quality_config=_test_config(),
            )
            self.assertTrue(result.passed)
            self.assertFalse(result.blocked)
            self.assertTrue(historical_quality_report_path(tmp).is_file())
            self.assertTrue(production_5y_collection_report_path("XAUUSD", tmp).is_file())

    def test_failed_validation_blocks_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = MLDataPipeline(base_dir=tmp)
            result = run_production_5y(
                pipe,
                "XAUUSD",
                days=30,
                validate_only=True,
                quality_config=_test_config(),
            )
            self.assertFalse(result.passed)
            self.assertTrue(result.blocked)

    def test_resume_state_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CollectionStateStore(tmp)
            state = store.new_state("XAUUSD", "M5", run_id="prod5y")
            state.completed_chunks = ["chunk_a"]
            path = store.save(state)
            reloaded = store.load("XAUUSD", "M5")
            assert reloaded is not None
            self.assertIn("chunk_a", reloaded.completed_chunks)
            self.assertTrue(path.is_file())


class TestForbiddenImports(unittest.TestCase):
    def test_no_forbidden_imports_or_mt5_writes(self):
        violations = _scan_files(PHASE88_FILES)
        self.assertEqual(violations, [], msg=str(violations))


class TestSyntheticFiveYearValidation(unittest.TestCase):
    def test_synthetic_dataset_meets_test_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = _store_aligned_5y_synthetic(tmp, days=40)
            cfg = _test_config()
            report = HistoricalQualityValidator(tmp, cfg).validate_all(
                "XAUUSD",
                expected_start=start,
                expected_end=start + timedelta(days=40),
            )
            self.assertTrue(report.passed)
            for tf in ("M5", "M15", "H4"):
                self.assertEqual(report.timeframes[tf].status, "PASS")


if __name__ == "__main__":
    unittest.main()
