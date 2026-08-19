"""Phase 2 feature engineering tests — causality, registry, pipeline compatibility."""

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

from tradingbot.ml.data.paths import features_dir
from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.features import FeatureBuilder, FeatureStore, all_features, feature_names, validate_integrity
from tradingbot.ml.features.align import closed_htf_index, closed_htf_slice
from tradingbot.ml.features.registry import export_json


def _ohlcv(n: int = 200, freq: str = "5min", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
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


class TestFeatureRegistry(unittest.TestCase):
    def test_registry_integrity(self):
        errors = validate_integrity()
        self.assertEqual(errors, [], msg=f"Registry errors: {errors}")
        names = feature_names()
        self.assertGreater(len(names), 30)
        self.assertEqual(len(names), len(set(names)))

    def test_registry_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = export_json(Path(tmp) / "features.json")
            self.assertTrue(path.is_file())
            payload = path.read_text(encoding="utf-8")
            self.assertIn("atr_percentile", payload)

    def test_all_families_registered(self):
        families = {f.family for f in all_features()}
        expected = {
            "trend",
            "momentum",
            "volatility",
            "price_action",
            "smc_structure",
            "htf_context",
            "session",
            "microstructure",
        }
        self.assertTrue(expected.issubset(families))


class TestCausalFeatures(unittest.TestCase):
    def setUp(self):
        self.m5 = _ohlcv(150, freq="5min")
        self.h4 = _ohlcv(80, freq="4h", seed=7)
        self.m15 = _ohlcv(100, freq="15min", seed=3)
        self.builder = FeatureBuilder("XAUUSD")

    def test_no_lookahead_at_index(self):
        idx = 100
        base = self.builder.compute_at(self.m5, idx, h4_df=self.h4, m15_df=self.m15)
        corrupted = copy.deepcopy(self.m5)
        corrupted.iloc[idx + 1 :, corrupted.columns.get_loc("close")] *= 1.5
        after = self.builder.compute_at(corrupted, idx, h4_df=self.h4, m15_df=self.m15)
        for key in base:
            self.assertAlmostEqual(base[key], after[key], places=4, msg=f"lookahead in {key}")

    def test_prefix_invariance(self):
        idx = 90
        short = self.m5.iloc[: idx + 1]
        full = self.m5
        f_short = self.builder.compute_at(short, idx, h4_df=self.h4.iloc[:40], m15_df=self.m15.iloc[:50])
        f_full = self.builder.compute_at(full, idx, h4_df=self.h4, m15_df=self.m15)
        for key in ("rsi_14", "atr_percentile", "body_ratio", "session_london"):
            self.assertAlmostEqual(f_short[key], f_full[key], places=4, msg=key)

    def test_htf_closed_bar_only(self):
        ts = self.m5.index[80]
        h4_idx = closed_htf_index(self.h4, ts, "H4")
        self.assertIsNotNone(h4_idx)
        sl = closed_htf_slice(self.h4, ts, "H4")
        self.assertIsNotNone(sl)
        self.assertLessEqual(len(sl), h4_idx + 1)


class TestDeterministicOutput(unittest.TestCase):
    def test_same_input_same_output(self):
        m5 = _ohlcv(120)
        b1 = FeatureBuilder("XAUUSD")
        b2 = FeatureBuilder("XAUUSD")
        f1 = b1.compute_at(m5, 100)
        f2 = b2.compute_at(m5, 100)
        self.assertEqual(f1, f2)

    def test_build_dataframe_columns(self):
        m5 = _ohlcv(130)
        builder = FeatureBuilder("XAUUSD")
        df = builder.build_dataframe(m5, h4_df=_ohlcv(60, "4h"), m15_df=_ohlcv(80, "15min"))
        self.assertGreater(len(df), 0)
        for name in feature_names():
            self.assertIn(name, df.columns, msg=f"missing column {name}")


class TestStorageSeparation(unittest.TestCase):
    def test_features_under_processed_not_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FeatureStore(tmp)
            m5 = _ohlcv(80)
            builder = FeatureBuilder("XAUUSD", base_dir=tmp)
            feats = builder.build_dataframe(m5)
            path = store.store("XAUUSD", "M5", feats)
            norm = str(path).replace("\\", "/")
            self.assertIn("processed", norm)
            self.assertIn("features", norm)
            self.assertNotIn("/raw/", norm)
            self.assertTrue(features_dir(tmp).is_dir())


class TestPipelineCompatibility(unittest.TestCase):
    def test_build_features_from_cached_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = CandleStore(tmp)
            m5 = _ohlcv(130)
            h4 = _ohlcv(70, "4h", seed=1)
            m15 = _ohlcv(90, "15min", seed=2)
            candles.store("XAUUSD", "M5", m5)
            candles.store("XAUUSD", "H4", h4)
            candles.store("XAUUSD", "M15", m15)

            pipe = MLDataPipeline({"MT5_LOGIN": None, "MT5_PASSWORD": "", "MT5_SERVER": ""}, base_dir=tmp)
            path = pipe.build_features("XAUUSD")
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.is_file())
            loaded = FeatureStore(tmp).load("XAUUSD", "M5")
            assert loaded is not None
            self.assertGreater(len(loaded.columns), 30)


class TestRequiredFeatures(unittest.TestCase):
    def test_smc_and_context_features_present(self):
        names = set(feature_names())
        required = {
            "bos_state",
            "choch_state",
            "liquidity_sweep",
            "fvg_presence",
            "order_block_distance",
            "premium_discount_location",
            "structure_distance",
            "h4_trend_bias",
            "h4_structure_direction",
            "m15_market_state",
            "m5_entry_context",
        }
        self.assertTrue(required.issubset(names))


class TestKernelUntouched(unittest.TestCase):
    def test_import_kernel_risk_execution(self):
        from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter  # noqa: F401
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401


if __name__ == "__main__":
    unittest.main()
