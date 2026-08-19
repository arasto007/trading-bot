"""Phase 15K — shared trend bar iteration and probability helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np
import pandas as pd

from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle, load_trend_bundle
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


@dataclass
class Phase15KContext:
    bundle: TrendRfBundle
    live_rows: list[dict[str, Any]]
    train_samples: pd.DataFrame

    @classmethod
    def build(
        cls,
        candles: pd.DataFrame,
        dataset: pd.DataFrame,
        *,
        base_dir: str | None = None,
        symbol: str = "XAUUSD",
        days: int = 365,
        stride: int = 15,
    ) -> Phase15KContext:
        bundle = load_frozen_bundle(base_dir=base_dir)
        live_rows = collect_trend_probabilities(
            candles, dataset, bundle, days=days, stride=stride,
        )
        train_frame = build_ml_features(candles)
        if len(train_frame) > 50_000:
            train_samples = train_frame.sample(n=50_000, random_state=42)
        else:
            train_samples = train_frame
        return cls(bundle=bundle, live_rows=live_rows, train_samples=train_samples)


def load_frozen_bundle(*, base_dir: str | None = None) -> TrendRfBundle:
    return load_trend_bundle(base_dir=base_dir, build_if_missing=False)


def iter_trend_bars(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int | None = 365,
    stride: int = 15,
) -> Iterator[tuple[int, pd.Series, pd.Timestamp]]:
    if days is not None:
        window = prepare_calibration_candles(candles, days=days)
    else:
        window = candles.copy()
    unified = build_unified_frame(window, dataset)
    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        if rule_classify_row(row) != "TREND":
            continue
        ts = pd.to_datetime(row.get("timestamp", unified.iloc[i].name), utc=True)
        yield i, row, ts


def bundle_probability(bundle: TrendRfBundle, row: pd.Series) -> float:
    feats = {k: float(row.get(k, 0.0)) for k in bundle.feature_order}
    return float(bundle.predict_proba(feats))


def filter_probability(row: pd.Series, bundle: TrendRfBundle) -> float:
    out = apply_trend_ml_filter(
        row, model=bundle.model, scaler=bundle.scaler,
        model_name="random_forest", threshold=float(bundle.config.get("threshold", 0.40)),
    )
    return float(out["probability"])


def sample_training_probabilities(
    bundle: TrendRfBundle,
    train_samples: pd.DataFrame,
    *,
    max_samples: int = 5000,
    seed: int = 42,
) -> list[float]:
    if train_samples.empty:
        return []
    n = min(max_samples, len(train_samples))
    subset = train_samples.sample(n=n, random_state=seed)
    probs: list[float] = []
    for _, srow in subset.iterrows():
        feats = {k: float(srow.get(k, 0.0)) for k in bundle.feature_order}
        probs.append(float(bundle.predict_proba(feats)))
    return probs


def collect_trend_probabilities(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    bundle: TrendRfBundle,
    *,
    days: int | None = 365,
    stride: int = 15,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _i, row, ts in iter_trend_bars(candles, dataset, days=days, stride=stride):
        prob = bundle_probability(bundle, row)
        rows.append({
            "timestamp": str(ts),
            "year": int(ts.year),
            "probability": prob,
            "features": {k: float(row.get(k, 0.0)) for k in bundle.feature_order},
        })
    return rows
