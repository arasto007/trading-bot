"""Phase 15K — trend RF probability ceiling analyzer."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase15k.config import OBSERVED_CEILING, TREND_THRESHOLD, dist_stats, pearson_corr
from tradingbot.ml.research.phase15k.data_access import (
    Phase15KContext,
    sample_training_probabilities,
)


def analyze_trend_ceiling(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    days: int = 365,
    stride: int = 15,
    ctx: Phase15KContext | None = None,
) -> dict[str, Any]:
    if ctx is None:
        ctx = Phase15KContext.build(
            candles, dataset, base_dir=base_dir, symbol=symbol, days=days, stride=stride,
        )
    bundle = ctx.bundle
    live_rows = ctx.live_rows
    train_samples = ctx.train_samples
    live_probs = [r["probability"] for r in live_rows]
    train_probs = sample_training_probabilities(bundle, train_samples)

    by_year: dict[str, dict[str, float]] = {}
    for year in range(2021, 2027):
        y_probs = [r["probability"] for r in live_rows if r["year"] == year]
        if y_probs:
            by_year[str(year)] = dist_stats(y_probs)

    feature_order = bundle.feature_order
    corr_with_prob: dict[str, float] = {}
    if live_rows:
        prob_arr = np.array(live_probs)
        for feat in feature_order:
            vals = np.array([r["features"][feat] for r in live_rows])
            corr_with_prob[feat] = round(pearson_corr(vals, prob_arr), 6)

    quantile_buckets: dict[str, dict[str, float]] = {}
    if live_rows and feature_order:
        anchor = feature_order[0]
        vals = np.array([r["features"][anchor] for r in live_rows])
        probs = np.array(live_probs)
        for q_lo, q_hi, label in ((0, 0.33, "low"), (0.33, 0.66, "mid"), (0.66, 1.01, "high")):
            lo, hi = np.quantile(vals, q_lo), np.quantile(vals, min(q_hi, 1.0))
            mask = (vals >= lo) & (vals <= hi) if q_hi < 1.0 else vals >= lo
            bucket_probs = probs[mask]
            if len(bucket_probs):
                quantile_buckets[f"{anchor}_{label}"] = dist_stats(bucket_probs)

    live_max = max(live_probs) if live_probs else 0.0
    train_max = max(train_probs) if train_probs else 0.0

    return {
        "phase": "15K",
        "threshold": TREND_THRESHOLD,
        "observed_ceiling_phase15j": OBSERVED_CEILING,
        "live_trend_distribution": dist_stats(live_probs),
        "training_distribution": dist_stats(train_probs),
        "training_sample_size": len(train_probs),
        "max_per_year": by_year,
        "max_trend_regime": dist_stats(live_probs),
        "probability_shift_train_vs_live": {
            "train_max": round(train_max, 6),
            "live_max": round(live_max, 6),
            "max_delta": round(train_max - live_max, 6),
            "live_below_threshold": live_max < TREND_THRESHOLD,
        },
        "feature_correlation_with_probability": corr_with_prob,
        "quantile_bucket_max": quantile_buckets,
        "mathematical_bound": {
            "statement": "P(trend_rf) <= live_max because RF predict_proba is bounded [0,1]; "
                           "empirical live ceiling equals max leaf-weighted vote on observed TREND bars",
            "live_empirical_max": round(live_max, 6),
            "gap_to_threshold": round(TREND_THRESHOLD - live_max, 6),
        },
    }
