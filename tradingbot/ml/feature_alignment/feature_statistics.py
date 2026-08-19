"""Phase 16A — frozen training and live reference statistics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS, build_ml_features
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.feature_alignment.config import (
    DEFAULT_CALIBRATION_DAYS,
    DEFAULT_QUANTILE_KNOTS,
    SHIFTED_FEATURES,
)


@dataclass
class FeatureStats:
    feature: str
    min: float
    max: float
    mean: float
    std: float
    quantiles: np.ndarray

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "min": round(float(self.min), 8),
            "max": round(float(self.max), 8),
            "mean": round(float(self.mean), 8),
            "std": round(float(self.std), 8),
            "quantile_grid": [round(float(x), 8) for x in self.quantiles],
        }


def _compute_stats(series: pd.Series, *, knots: int) -> FeatureStats:
    vals = series.dropna().astype(float).values
    if len(vals) == 0:
        z = np.zeros(knots)
        return FeatureStats(feature=str(series.name), min=0.0, max=0.0, mean=0.0, std=0.0, quantiles=z)
    ps = np.linspace(0.0, 1.0, knots)
    q = np.quantile(vals, ps)
    return FeatureStats(
        feature=str(series.name),
        min=float(np.min(vals)),
        max=float(np.max(vals)),
        mean=float(np.mean(vals)),
        std=float(np.std(vals)),
        quantiles=q.astype(float),
    )


def load_training_statistics(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    knots: int = DEFAULT_QUANTILE_KNOTS,
    shifted_only: bool = True,
) -> dict[str, FeatureStats]:
    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    frame = build_ml_features(candles)
    features = SHIFTED_FEATURES if shifted_only else TREND_ML_FEATURE_COLUMNS
    out: dict[str, FeatureStats] = {}
    for feat in features:
        if feat not in frame.columns:
            continue
        out[feat] = _compute_stats(frame[feat].rename(feat), knots=knots)
    return out


def load_live_reference_statistics(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = DEFAULT_CALIBRATION_DAYS,
    knots: int = DEFAULT_QUANTILE_KNOTS,
    shifted_only: bool = True,
) -> dict[str, FeatureStats]:
    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset if dataset is not None else pd.DataFrame())
    trend = unified[unified.apply(rule_classify_row, axis=1) == "TREND"]
    features = SHIFTED_FEATURES if shifted_only else TREND_ML_FEATURE_COLUMNS
    out: dict[str, FeatureStats] = {}
    for feat in features:
        if feat not in trend.columns:
            continue
        out[feat] = _compute_stats(trend[feat].rename(feat), knots=knots)
    return out


def statistics_snapshot(
    train: dict[str, FeatureStats],
    live: dict[str, FeatureStats],
) -> dict[str, Any]:
    rows = []
    for feat in SHIFTED_FEATURES:
        tr = train.get(feat)
        lv = live.get(feat)
        if tr is None or lv is None:
            continue
        rows.append({
            "feature": feat,
            "training_mean": tr.mean,
            "live_mean": lv.mean,
            "training_std": tr.std,
            "live_std": lv.std,
            "mean_delta_before": round(lv.mean - tr.mean, 8),
        })
    return {"shifted_features": list(SHIFTED_FEATURES), "per_feature": rows}
