"""Phase 22D — pipeline and v41 engine fix tests."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from tradingbot.ml.research.phase17b.config import TOP5_FEATURES


@pytest.fixture
def v41_env(monkeypatch):
    monkeypatch.setenv("TREND_MODEL_VERSION", "v41")


def test_pipeline_cache_attaches_top5_when_v41(v41_env):
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
    from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels

    PipelineCache.reset()
    n = 400
    unified = build_ml_features(_synthetic_candles(n))
    unified["regime"] = attach_regime_labels(unified).values
    enriched = PipelineCache._attach_trend_v41_features(unified)
    for feat in TOP5_FEATURES:
        assert feat in enriched.columns, f"missing {feat}"
    assert enriched["trend_age"].max() > 1


def test_v41_engine_requires_preattached_top5(v41_env):
    from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
    from tradingbot.ml.phase17d.v41_engine import TrendRfV41Engine
    from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a

    bundle = load_trend_bundle(version="v41")
    eng = TrendRfV41Engine(bundle=bundle, threshold=0.4, rule_fn=evaluate_variant_a)
    row = pd.Series({"adx": 30, "ema20": 1.1, "ema50": 1.0, "ema50_slope": 0.2, "ema20_slope": 0.1,
                     "higher_high_count": 3, "lower_low_count": 0, "close": 1.0, "atr": 0.01})
    with pytest.raises(ValueError, match="missing features"):
        eng._enriched_row(row)


def _synthetic_candles(n: int) -> pd.DataFrame:
    import numpy as np

    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = 2000 + np.cumsum(np.random.default_rng(42).normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 100.0,
        }
    )
