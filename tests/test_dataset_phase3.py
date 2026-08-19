"""Phase 3 dataset construction and labeling tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import dataset_path, dataset_quality_report_path
from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.stores import CandleStore, EventStore
from tradingbot.ml.dataset import (
    DatasetBuilder,
    DatasetBuildConfig,
    DatasetStore,
    Label,
    assign_split_column,
    label_from_future_candles,
    time_based_split,
    validate_dataset,
    validate_dataset_schema,
    verify_chronological_splits,
    verify_rr_ratio,
)
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.features import FeatureBuilder, FeatureStore, feature_names


def _flat_candles(n: int = 30, base: float = 100.0, atr_range: float = 20.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    half = atr_range / 2
    return pd.DataFrame(
        {
            "open": base,
            "high": base + half,
            "low": base - half,
            "close": base,
            "volume": 10,
        },
        index=idx,
    )


def _long_tp_scenario() -> pd.DataFrame:
    df = _flat_candles(25, base=100.0, atr_range=20.0)
    # entry at bar 14; R~20 -> SL=80 TP=140
    i = 14
    df.iloc[i + 1, df.columns.get_loc("high")] = 150.0
    df.iloc[i + 1, df.columns.get_loc("low")] = 95.0
    df.iloc[i + 1, df.columns.get_loc("close")] = 145.0
    return df


def _long_sl_scenario() -> pd.DataFrame:
    df = _flat_candles(25, base=100.0, atr_range=20.0)
    i = 14
    df.iloc[i + 1, df.columns.get_loc("high")] = 105.0
    df.iloc[i + 1, df.columns.get_loc("low")] = 75.0
    df.iloc[i + 1, df.columns.get_loc("close")] = 78.0
    return df


def _ohlcv(n: int = 150, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
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


class TestLabeling(unittest.TestCase):
    def test_tp_hit_before_sl_long(self):
        df = _long_tp_scenario()
        result = label_from_future_candles(df, 14, 1, future_window_bars=10)
        self.assertEqual(result.label, int(Label.TP_FIRST))
        self.assertTrue(result.tp_hit)
        self.assertFalse(result.sl_hit)

    def test_sl_hit_before_tp_long(self):
        df = _long_sl_scenario()
        result = label_from_future_candles(df, 14, 1, future_window_bars=10)
        self.assertEqual(result.label, int(Label.SL_FIRST))
        self.assertTrue(result.sl_hit)
        self.assertFalse(result.tp_hit)

    def test_no_resolution(self):
        df = _flat_candles(30)
        result = label_from_future_candles(df, 19, 1, future_window_bars=5)
        self.assertEqual(result.label, int(Label.NO_RESOLUTION))

    def test_rr_ratio_1_to_2(self):
        df = _flat_candles(20)
        result = label_from_future_candles(df, 10, 1, future_window_bars=5)
        self.assertTrue(verify_rr_ratio(result))
        tp_dist = abs(result.take_profit - result.entry_price)
        sl_dist = abs(result.stop_loss - result.entry_price)
        self.assertAlmostEqual(tp_dist / sl_dist, 2.0, places=4)

    def test_mfe_mae_positive(self):
        df = _long_tp_scenario()
        result = label_from_future_candles(df, 14, 1, future_window_bars=10)
        self.assertGreater(result.mfe, 0)
        self.assertGreaterEqual(result.mae, 0)


class TestChronologicalSplit(unittest.TestCase):
    def test_split_ratios(self):
        ts = pd.date_range("2022-01-01", periods=100, freq="D", tz="UTC")
        df = pd.DataFrame({"timestamp": ts, "value": range(100)})
        split = time_based_split(df)
        self.assertEqual(len(split.train), 70)
        self.assertEqual(len(split.validation), 15)
        self.assertEqual(len(split.test), 15)

    def test_no_shuffle_chronological(self):
        ts = pd.date_range("2022-01-01", periods=100, freq="D", tz="UTC")
        df = pd.DataFrame({"timestamp": ts, "label": range(100)})
        df = assign_split_column(df)
        self.assertTrue(verify_chronological_splits(df))

    def test_train_ends_before_validation(self):
        ts = pd.date_range("2022-01-01", periods=100, freq="D", tz="UTC")
        df = pd.DataFrame({"timestamp": ts})
        df = assign_split_column(df)
        train_max = pd.to_datetime(df[df["split"] == "train"]["timestamp"]).max()
        val_min = pd.to_datetime(df[df["split"] == "validation"]["timestamp"]).min()
        self.assertLess(train_max, val_min)


class TestDatasetSchema(unittest.TestCase):
    def test_required_columns_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = CandleStore(tmp)
            features = FeatureStore(tmp)
            m5 = _ohlcv(130)
            candles.store("XAUUSD", "M5", m5)
            builder_f = FeatureBuilder("XAUUSD")
            feats = builder_f.build_dataframe(m5)
            features.store("XAUUSD", "M5", feats)
            events = EventStore(tmp)
            _write_event(
                events,
                "XAUUSD",
                "M5",
                [
                    {
                        "event_id": "e1",
                        "event_type": "bos",
                        "ts_utc": m5.index[80].isoformat(),
                        "direction": 1,
                        "price": float(m5["close"].iloc[80]),
                        "metadata": {"bar_index": 80},
                    }
                ],
            )
            cfg = DatasetBuildConfig(symbol="XAUUSD", timeframe="M5", future_window_bars=20)
            ds = DatasetBuilder(cfg, base_dir=tmp).build()
            errors = validate_dataset_schema(ds)
            self.assertEqual(errors, [], msg=str(errors))
            self.assertIn("dataset_schema_version", ds.columns)
            self.assertEqual(ds["dataset_schema_version"].iloc[0], DATASET_SCHEMA_VERSION)


class TestEventSampling(unittest.TestCase):
    def test_only_event_based_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = CandleStore(tmp)
            features = FeatureStore(tmp)
            m5 = _ohlcv(130)
            candles.store("XAUUSD", "M5", m5)
            feats = FeatureBuilder("XAUUSD").build_dataframe(m5)
            features.store("XAUUSD", "M5", feats)
            events = EventStore(tmp)
            _write_event(
                events,
                "XAUUSD",
                "M5",
                [
                    {
                        "event_id": "bos1",
                        "event_type": "bos",
                        "ts_utc": m5.index[70].isoformat(),
                        "direction": 1,
                        "metadata": {"bar_index": 70},
                    },
                    {
                        "event_id": "fvg1",
                        "event_type": "fvg",
                        "ts_utc": m5.index[90].isoformat(),
                        "direction": -1,
                        "metadata": {"bar_index": 90},
                    },
                ],
            )
            ds = DatasetBuilder(DatasetBuildConfig(future_window_bars=15), base_dir=tmp).build()
            self.assertGreaterEqual(len(ds), 2)
            self.assertTrue(set(ds["event_type"]).issubset({"bos", "choch", "fvg", "order_block", "liquidity_sweep", "trading_session", "session_transition"}))


class TestReproducibility(unittest.TestCase):
    def test_deterministic_dataset_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = CandleStore(tmp)
            features = FeatureStore(tmp)
            m5 = _ohlcv(120, seed=5)
            candles.store("XAUUSD", "M5", m5)
            feats = FeatureBuilder("XAUUSD").build_dataframe(m5)
            features.store("XAUUSD", "M5", feats)
            events = EventStore(tmp)
            _write_event(
                events,
                "XAUUSD",
                "M5",
                [
                    {
                        "event_id": "x1",
                        "event_type": "choch",
                        "ts_utc": m5.index[75].isoformat(),
                        "direction": -1,
                        "metadata": {"bar_index": 75},
                    }
                ],
            )
            cfg = DatasetBuildConfig(future_window_bars=10)
            b = DatasetBuilder(cfg, base_dir=tmp)
            d1 = b.build()
            d2 = b.build()
            pd.testing.assert_frame_equal(
                d1.sort_values("timestamp").reset_index(drop=True),
                d2.sort_values("timestamp").reset_index(drop=True),
            )

    def test_build_manifest_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = CandleStore(tmp)
            features = FeatureStore(tmp)
            m5 = _ohlcv(120)
            candles.store("XAUUSD", "M5", m5)
            feats = FeatureBuilder("XAUUSD").build_dataframe(m5)
            features.store("XAUUSD", "M5", feats)
            events = EventStore(tmp)
            _write_event(
                events,
                "XAUUSD",
                "M5",
                [
                    {
                        "event_id": "m1",
                        "event_type": "bos",
                        "ts_utc": m5.index[70].isoformat(),
                        "direction": 1,
                        "metadata": {"bar_index": 70},
                    }
                ],
            )
            pipe = MLDataPipeline({"MT5_LOGIN": None, "MT5_PASSWORD": "", "MT5_SERVER": ""}, base_dir=tmp)
            path = pipe.build_dataset("XAUUSD")
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.is_file())
            store = DatasetStore(tmp)
            manifest = store.load_build_manifest("XAUUSD", "M5")
            self.assertIn("source_candle_hash", manifest)
            self.assertIn("build_timestamp_utc", manifest)


class TestDatasetStorage(unittest.TestCase):
    def test_stored_under_datasets(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = pd.DataFrame(
                {
                    "timestamp": pd.date_range("2026-01-01", periods=5, freq="5min", tz="UTC"),
                    "symbol": "XAUUSD",
                    "timeframe": "M5",
                    "event_type": "bos",
                    "event_time": "t",
                    "entry_price": 1.0,
                    "timeframe_role": "entry_execution",
                    "stop_loss": 0.9,
                    "take_profit": 1.2,
                    "label": 1,
                    "future_window_bars": 72,
                    "tp_hit": True,
                    "sl_hit": False,
                    "mfe": 1.0,
                    "mae": 0.1,
                    "future_return": 0.01,
                    "dataset_schema_version": DATASET_SCHEMA_VERSION,
                }
            )
            store = DatasetStore(tmp)
            path = store.store("XAUUSD", "M5", df)
            norm = str(path).replace("\\", "/")
            self.assertIn("datasets", norm)
            self.assertTrue(dataset_path("XAUUSD", "M5", tmp).is_file())


class TestKernelUntouched(unittest.TestCase):
    def test_import_kernel_risk_execution(self):
        from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter  # noqa: F401
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401


if __name__ == "__main__":
    unittest.main()
