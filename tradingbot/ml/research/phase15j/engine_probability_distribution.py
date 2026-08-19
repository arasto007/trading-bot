"""Phase 15J — engine probability distribution."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


def _dist_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "std": 0.0, "min": 0.0, "max": 0.0,
                "p95": 0.0, "p99": 0.0}
    arr = np.array(values, dtype=float)
    return {
        "count": len(values),
        "mean": round(float(np.mean(arr)), 6),
        "median": round(float(np.median(arr)), 6),
        "std": round(float(np.std(arr)), 6),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
        "p95": round(float(np.percentile(arr, 95)), 6),
        "p99": round(float(np.percentile(arr, 99)), 6),
    }


def _histogram(values: list[float], bins: int = 20) -> list[dict[str, float]]:
    if not values:
        return []
    counts, edges = np.histogram(values, bins=bins, range=(0.0, 1.0))
    return [
        {"bin_start": round(float(edges[i]), 4), "bin_end": round(float(edges[i + 1]), 4), "count": int(counts[i])}
        for i in range(len(counts))
    ]


def analyze_probability_distribution(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    days: int = 365,
    stride: int = 15,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    threshold = float(bundle.config.get("threshold", 0.40))

    all_probs: list[float] = []
    buy_probs: list[float] = []
    sell_probs: list[float] = []
    buy_n = sell_n = hold_n = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        if rule_classify_row(row) != "TREND":
            continue
        ml = apply_trend_ml_filter(
            row, model=bundle.model, scaler=bundle.scaler,
            model_name="random_forest", threshold=threshold,
        )
        prob = float(ml["probability"])
        rule = evaluate_variant_a(row, regime="TREND")
        all_probs.append(prob)
        if rule == "BUY":
            buy_probs.append(prob)
            buy_n += 1
        elif rule == "SELL":
            sell_probs.append(prob)
            sell_n += 1
        else:
            hold_n += 1

    total = buy_n + sell_n + hold_n or 1
    actionable_pct = (buy_n + sell_n) / total
    flags: list[str] = []
    if actionable_pct < 0.05:
        flags.append("ENGINE_COLLAPSE")
    if all_probs and max(all_probs) < threshold:
        flags.append("PROBABILITY_COLLAPSE")

    return {
        "phase": "15J",
        "threshold": threshold,
        "all_probabilities": _dist_stats(all_probs),
        "buy_probability": _dist_stats(buy_probs),
        "sell_probability": _dist_stats(sell_probs),
        "histogram_all": _histogram(all_probs),
        "histogram_buy": _histogram(buy_probs),
        "histogram_sell": _histogram(sell_probs),
        "class_distribution": {
            "BUY_pct": round(buy_n / total, 4),
            "SELL_pct": round(sell_n / total, 4),
            "HOLD_pct": round(hold_n / total, 4),
        },
        "actionable_pct": round(actionable_pct, 4),
        "flags": flags,
    }
