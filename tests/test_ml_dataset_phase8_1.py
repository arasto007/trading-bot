"""Phase 8.1 production dataset build tests (no MT5 required)."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.stores import CandleStore, EventStore
from tradingbot.ml.dataset import (
    DatasetBuildConfig,
    DatasetStore,
    validate_dataset_schema,
    verify_chronological_splits,
)
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor
from tradingbot.ml.dataset.preflight import run_preflight
from tradingbot.ml.dataset.production_builder import ProductionDatasetBuilder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.features import feature_names

DATASET_PKG = ROOT / "tradingbot" / "ml" / "dataset"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
)

_TEST_MINIMUMS = {"M5": 100, "M15": 40, "H4": 10}


def _scan_files(filenames: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for name in filenames:
        path = DATASET_PKG / name
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


def _ohlcv(n: int, *, freq: str = "5min", start: str = "2024-01-01", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    close = 2300 + np.cumsum(rng.normal(0, 0.3, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + rng.uniform(0.2, 0.8, n),
            "low": close - rng.uniform(0.2, 0.8, n),
            "close": close,
            "volume": rng.integers(5, 50, n),
        },
        index=idx,
    )


def _write_event(store: EventStore, symbol: str, tf: str, events: list[dict]) -> None:
    from tradingbot.ml.data.schema import MarketEvent

    objs = [
        MarketEvent(
            event_id=e["event_id"],
            event_type=e["event_type"],
            symbol=symbol,
            timeframe=tf,
            ts_utc=e["ts_utc"],
            direction=e.get("direction", 0),
            price=e.get("price", 0.0),
            metadata=e.get("metadata", {}),
        )
        for e in events
    ]
    store.append(objs, dedupe=False)


def _seed_raw_tiers(tmp: str, *, m5_bars: int = 300) -> tuple[pd.DataFrame, CandleStore, EventStore]:
    candles = CandleStore(tmp)
    events = EventStore(tmp)
    start = "2024-01-01"
    m5 = _ohlcv(m5_bars, freq="5min", start=start, seed=1)
    m15 = _ohlcv(max(m5_bars // 3, 60), freq="15min", start=start, seed=2)
    h4 = _ohlcv(max(m5_bars // 48, 15), freq="4h", start=start, seed=3)
    candles.store("XAUUSD", "M5", m5)
    candles.store("XAUUSD", "M15", m15)
    candles.store("XAUUSD", "H4", h4)
    _write_event(
        events,
        "XAUUSD",
        "M5",
        [
            {
                "event_id": "e1",
                "event_type": "bos",
                "ts_utc": m5.index[120].isoformat(),
                "direction": 1,
                "price": float(m5["close"].iloc[120]),
                "metadata": {"bar_index": 120},
            },
            {
                "event_id": "e2",
                "event_type": "fvg",
                "ts_utc": m5.index[150].isoformat(),
                "direction": -1,
                "price": float(m5["close"].iloc[150]),
                "metadata": {"bar_index": 150},
            },
        ],
    )
    _write_event(
        events,
        "XAUUSD",
        "M15",
        [
            {
                "event_id": "m15e1",
                "event_type": "choch",
                "ts_utc": m15.index[30].isoformat(),
                "direction": -1,
                "metadata": {"bar_index": 30},
            },
        ],
    )
    return m5, candles, events


class TestPreflightFailure(unittest.TestCase):
    def test_preflight_fails_without_raw_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_preflight(
                "XAUUSD",
                base_dir=tmp,
                minimum_overrides=_TEST_MINIMUMS,
                min_overlap_days=1,
            )
            self.assertFalse(report.passed)
            self.assertEqual(report.overall, "fail")
            self.assertTrue(any("no raw candle" in i or "no_data" in i for i in report.issues))


class TestPreflightSuccess(unittest.TestCase):
    def test_preflight_passes_with_synthetic_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_raw_tiers(tmp)
            report = run_preflight(
                "XAUUSD",
                base_dir=tmp,
                minimum_overrides=_TEST_MINIMUMS,
                min_overlap_days=1,
            )
            self.assertTrue(report.passed)
            self.assertGreaterEqual(report.overlap_days, 1.0)
            self.assertTrue(report.timeframes["M5"].meets_minimum)


class TestProductionBuild(unittest.TestCase):
    def test_full_build_produces_labeled_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            m5, _, _ = _seed_raw_tiers(tmp, m5_bars=300)
            cfg = DatasetBuildConfig(symbol="XAUUSD", timeframe="M5", future_window_bars=20)
            builder = ProductionDatasetBuilder(
                "XAUUSD",
                timeframe="M5",
                base_dir=tmp,
                config=cfg,
                minimum_overrides=_TEST_MINIMUMS,
                min_overlap_days=1,
            )
            result = builder.build()
            self.assertTrue(result.passed, msg=str(result.errors))
            self.assertIsNotNone(result.dataset_path)
            self.assertIsNotNone(result.features_path)
            self.assertIsNotNone(result.manifest_path)

            store = DatasetStore(tmp)
            df = store.load("XAUUSD", "M5")
            self.assertIsNotNone(df)
            assert df is not None
            self.assertGreater(len(df), 0)
            self.assertIn("label", df.columns)
            self.assertIn("split", df.columns)
            feat_cols = [c for c in feature_names() if c in df.columns]
            self.assertGreater(len(feat_cols), 0)
            self.assertTrue(verify_chronological_splits(df))


class TestDatasetSchema(unittest.TestCase):
    def test_required_schema_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_raw_tiers(tmp, m5_bars=300)
            cfg = DatasetBuildConfig(future_window_bars=20)
            result = ProductionDatasetBuilder(
                "XAUUSD",
                base_dir=tmp,
                config=cfg,
                minimum_overrides=_TEST_MINIMUMS,
                min_overlap_days=1,
            ).build()
            self.assertTrue(result.passed)
            df = DatasetStore(tmp).load("XAUUSD", "M5")
            assert df is not None
            errors = validate_dataset_schema(df)
            self.assertEqual(errors, [], msg=str(errors))
            self.assertEqual(df["dataset_schema_version"].iloc[0], DATASET_SCHEMA_VERSION)


class TestLeakageProtection(unittest.TestCase):
    def test_leakage_audit_passes_on_built_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_raw_tiers(tmp, m5_bars=300)
            cfg = DatasetBuildConfig(future_window_bars=20)
            ProductionDatasetBuilder(
                "XAUUSD",
                base_dir=tmp,
                config=cfg,
                minimum_overrides=_TEST_MINIMUMS,
                min_overlap_days=1,
            ).build()
            df = DatasetStore(tmp).load("XAUUSD", "M5")
            assert df is not None
            audit = DatasetLeakageAuditor().audit(df, "XAUUSD", "M5")
            self.assertEqual(audit.status, "pass")


class TestFingerprint(unittest.TestCase):
    def test_fingerprint_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_raw_tiers(tmp, m5_bars=300)
            cfg = DatasetBuildConfig(future_window_bars=20)
            ProductionDatasetBuilder(
                "XAUUSD",
                base_dir=tmp,
                config=cfg,
                minimum_overrides=_TEST_MINIMUMS,
                min_overlap_days=1,
            ).build()
            df = DatasetStore(tmp).load("XAUUSD", "M5")
            assert df is not None
            fp1 = compute_dataset_fingerprint(df, cfg)
            fp2 = compute_dataset_fingerprint(df, cfg)
            self.assertEqual(fp1.dataset_hash, fp2.dataset_hash)
            self.assertEqual(fp1.feature_hash, fp2.feature_hash)


class TestValidateOnly(unittest.TestCase):
    def test_validate_existing_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_raw_tiers(tmp, m5_bars=300)
            cfg = DatasetBuildConfig(future_window_bars=20)
            builder = ProductionDatasetBuilder(
                "XAUUSD",
                base_dir=tmp,
                config=cfg,
                minimum_overrides=_TEST_MINIMUMS,
                min_overlap_days=1,
            )
            builder.build()
            report = builder.validate_existing()
            self.assertNotEqual(report["status"], "fail")
            self.assertIn("fingerprint", report)


class TestIsolation(unittest.TestCase):
    def test_no_forbidden_imports(self):
        violations = _scan_files(("preflight.py", "production_builder.py"))
        self.assertEqual(violations, [], msg=str(violations))

    def test_no_kernel_dependency(self):
        violations = _scan_files(("preflight.py", "production_builder.py"))
        kernel = [v for v in violations if "kernel" in v]
        self.assertEqual(kernel, [])

    def test_no_execution_dependency(self):
        violations = _scan_files(("preflight.py", "production_builder.py"))
        exec_hits = [v for v in violations if "execution" in v or "mt5_execution" in v]
        self.assertEqual(exec_hits, [])


if __name__ == "__main__":
    unittest.main()
