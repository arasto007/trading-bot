"""Mandatory no-leakage tests — features causal, labels use future only."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.schema import MarketEvent
from tradingbot.ml.data.stores import CandleStore, EventStore
from tradingbot.ml.dataset import DatasetBuilder, DatasetBuildConfig, label_from_future_candles
from tradingbot.ml.dataset.builder import _merge_features_at
from tradingbot.ml.features import FeatureBuilder, FeatureStore, feature_names


def _ohlcv(n: int = 130, seed: int = 42) -> pd.DataFrame:
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


class TestFeatureNoLeakage(unittest.TestCase):
    def test_features_unchanged_when_future_candles_corrupted(self):
        m5 = _ohlcv(130)
        builder = FeatureBuilder("XAUUSD")
        idx = 80
        ts = m5.index[idx]
        base_feats = builder.compute_at(m5, idx)

        corrupted = copy.deepcopy(m5)
        corrupted.iloc[idx + 1 :, corrupted.columns.get_loc("close")] *= 2.0
        after_feats = builder.compute_at(corrupted, idx)
        for name in feature_names():
            self.assertAlmostEqual(base_feats[name], after_feats[name], places=4, msg=name)

    def test_dataset_features_match_causal_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = CandleStore(tmp)
            features = FeatureStore(tmp)
            m5 = _ohlcv(130)
            candles.store("XAUUSD", "M5", m5)
            feat_df = FeatureBuilder("XAUUSD").build_dataframe(m5)
            features.store("XAUUSD", "M5", feat_df)

            events = EventStore(tmp)
            bar = 85
            events.append(
                [
                    MarketEvent(
                        event_id="leak_test",
                        event_type="bos",
                        symbol="XAUUSD",
                        timeframe="M5",
                        ts_utc=m5.index[bar].isoformat(),
                        direction=1,
                        metadata={"bar_index": bar},
                    )
                ],
                dedupe=False,
            )

            ds = DatasetBuilder(DatasetBuildConfig(future_window_bars=10), base_dir=tmp).build()
            row = ds[ds["event_id"] == "leak_test"].iloc[0]
            expected = _merge_features_at(feat_df, pd.Timestamp(m5.index[bar]), feature_names())
            for name in feature_names():
                if name in row.index:
                    self.assertAlmostEqual(float(row[name]), expected[name], places=4, msg=name)


class TestLabelUsesFutureOnly(unittest.TestCase):
    def test_label_window_starts_after_entry(self):
        df = _ohlcv(40)
        entry = 20
        result = label_from_future_candles(df, entry, 1, future_window_bars=10)
        if result.resolution_bar is not None:
            self.assertGreater(result.resolution_bar, entry)

    def test_atr_at_entry_uses_only_past_candles(self):
        """ATR/risk at entry is causal — computed from bars <= entry only."""
        df = _ohlcv(40)
        entry = 25
        base = label_from_future_candles(df, entry, 1, future_window_bars=5)
        future_corrupt = copy.deepcopy(df)
        future_corrupt.iloc[entry + 1 :, future_corrupt.columns.get_loc("close")] *= 3.0
        after = label_from_future_candles(future_corrupt, entry, 1, future_window_bars=5)
        self.assertEqual(base.risk_unit, after.risk_unit)
        self.assertEqual(base.stop_loss, after.stop_loss)
        self.assertEqual(base.take_profit, after.take_profit)

    def test_label_changes_when_future_changes(self):
        df = _ohlcv(40)
        entry = 20
        base = label_from_future_candles(df, entry, 1, future_window_bars=10)

        future_corrupt = copy.deepcopy(df)
        future_corrupt.iloc[entry + 1 :, future_corrupt.columns.get_loc("high")] = 9999.0
        future_corrupt.iloc[entry + 1 :, future_corrupt.columns.get_loc("low")] = 9998.0
        after_future = label_from_future_candles(future_corrupt, entry, 1, future_window_bars=10)
        # Future change should affect at least one outcome field
        changed = (
            base.label != after_future.label
            or base.tp_hit != after_future.tp_hit
            or base.mfe != after_future.mfe
        )
        self.assertTrue(changed)

    def test_entry_bar_excluded_from_label_window(self):
        df = _ohlcv(30)
        entry = 15
        # Spike only on entry bar should not count for labeling resolution
        df2 = copy.deepcopy(df)
        df2.iloc[entry, df2.columns.get_loc("high")] = 5000.0
        r1 = label_from_future_candles(df, entry, 1, future_window_bars=5)
        r2 = label_from_future_candles(df2, entry, 1, future_window_bars=5)
        self.assertEqual(r1.label, r2.label)


if __name__ == "__main__":
    unittest.main()
