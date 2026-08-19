"""Phase 22U — phase9_9 model capability verification."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

BUY_ZONE_MIN = 0.55
SELL_ZONE_MAX = 0.45
HIST_BIN_WIDTH = 0.05
FEATURES = ("ema50_slope", "candle_direction", "structure_distance")


def _json_float(v: Any) -> Any:
    if isinstance(v, (np.floating, float)):
        return round(float(v), 8)
    if isinstance(v, (np.integer, int)):
        return int(v)
    return v


def extract_model_weights(bundle) -> dict[str, Any]:
    model = bundle.model
    scaler = bundle.scaler
    features = list(bundle.feature_order)

    est = getattr(model, "_model", model)
    if hasattr(model, "_estimator"):
        est = model._estimator()

    weights: dict[str, Any] = {
        "model_type": type(model).__name__,
        "estimator_type": type(est).__name__,
        "feature_order": features,
        "classes": [int(c) for c in getattr(est, "classes_", getattr(model, "classes_", []))],
    }

    coef = getattr(est, "coef_", None)
    intercept = getattr(est, "intercept_", None)
    if coef is not None:
        coef_row = coef[0] if len(coef.shape) > 1 else coef
        weights["coefficients"] = {
            f: _json_float(coef_row[i]) for i, f in enumerate(features)
        }
        abs_coef = np.abs(coef_row)
        total = float(abs_coef.sum()) or 1.0
        weights["feature_importance_abs_coef_normalized"] = {
            f: round(float(abs_coef[i] / total), 6) for i, f in enumerate(features)
        }
    if intercept is not None:
        weights["intercept"] = _json_float(intercept[0] if hasattr(intercept, "__len__") else intercept)

    weights["scaler"] = {
        "mean": {f: _json_float(scaler.mean_[i]) for i, f in enumerate(features)},
        "scale": {f: _json_float(scaler.scale_[i]) for i, f in enumerate(features)},
    }
    weights["config"] = dict(bundle.config)
    weights["metadata"] = dict(bundle.metadata)
    return weights


def _zone_counts(probs: np.ndarray) -> dict[str, Any]:
    n = len(probs)
    if n == 0:
        return {"n": 0, "buy_zone_pct": 0.0, "sell_zone_pct": 0.0, "neutral_pct": 0.0}
    buy = int(np.sum(probs >= BUY_ZONE_MIN))
    sell = int(np.sum(probs <= SELL_ZONE_MAX))
    neutral = n - buy - sell
    return {
        "n": n,
        "buy_zone_count": buy,
        "sell_zone_count": sell,
        "neutral_count": neutral,
        "buy_zone_pct": round(buy / n * 100, 4),
        "sell_zone_pct": round(sell / n * 100, 4),
        "neutral_pct": round(neutral / n * 100, 4),
    }


def probability_histogram(probs: np.ndarray, *, bin_width: float = HIST_BIN_WIDTH) -> dict[str, Any]:
    edges = np.arange(0.0, 1.0 + bin_width, bin_width)
    counts, bin_edges = np.histogram(probs, bins=edges)
    bins = []
    for i, count in enumerate(counts):
        lo = round(float(bin_edges[i]), 2)
        hi = round(float(bin_edges[i + 1]), 2)
        bins.append({
            "range": f"{lo:.2f}-{hi:.2f}",
            "lo": lo,
            "hi": hi,
            "count": int(count),
            "pct": round(int(count) / max(len(probs), 1) * 100, 4),
        })
    return {
        "bin_width": bin_width,
        "total": len(probs),
        "bins": bins,
    }


def probability_stats(probs: np.ndarray) -> dict[str, Any]:
    if len(probs) == 0:
        return {}
    return {
        "mean": round(float(np.mean(probs)), 6),
        "std": round(float(np.std(probs)), 6),
        "median": round(float(np.median(probs)), 6),
        "min": round(float(np.min(probs)), 6),
        "max": round(float(np.max(probs)), 6),
        "p05": round(float(np.percentile(probs, 5)), 6),
        "p95": round(float(np.percentile(probs, 95)), 6),
        "pct_below_0_45": round(float(np.mean(probs <= SELL_ZONE_MAX)) * 100, 4),
        "pct_above_0_55": round(float(np.mean(probs >= BUY_ZONE_MIN)) * 100, 4),
        "pct_in_neutral_band": round(float(np.mean((probs > SELL_ZONE_MAX) & (probs < BUY_ZONE_MIN))) * 100, 4),
    }


def label_distribution(df: pd.DataFrame) -> dict[str, Any]:
    labels = df["label"].astype(int)
    n = len(labels)
    pos = int((labels == 1).sum())
    neg = int((labels == 0).sum())
    unresolved = int((labels == -1).sum())
    return {
        "total_rows": n,
        "positive_tp_first": pos,
        "negative_sl_first": neg,
        "unresolved_no_resolution": unresolved,
        "positive_pct": round(pos / max(n, 1) * 100, 4),
        "negative_pct": round(neg / max(n, 1) * 100, 4),
        "unresolved_pct": round(unresolved / max(n, 1) * 100, 4),
        "classes_present": sorted(labels.unique().tolist()),
    }


def raw_predict_all(bundle, df: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    features = list(bundle.feature_order)
    missing = [f for f in features if f not in df.columns]
    if missing:
        raise ValueError(f"dataset missing features: {missing}")

    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    X = work.loc[:, features].astype(np.float64)
    scaled = bundle.scaler.transform(X.values)
    proba = bundle.model.predict_proba(scaled)[:, 1]
    work["p_win_raw"] = proba
    return proba.astype(float), work


def filter_dataset_a_rows(df: pd.DataFrame, dataset_a) -> pd.DataFrame:
    from zoneinfo import ZoneInfo

    tehran = ZoneInfo("Asia/Tehran")
    ts = pd.to_datetime(df["timestamp"], utc=True)
    start = pd.Timestamp(dataset_a.start.astimezone(tehran)).tz_convert("UTC")
    end = pd.Timestamp(dataset_a.end.astimezone(tehran)).tz_convert("UTC")
    mask = (ts >= start) & (ts <= end)
    return df.loc[mask].copy()


def determine_verdict(
    training_zones: dict[str, Any],
    training_stats: dict[str, Any],
    dataset_a_zones: dict[str, Any] | None,
) -> tuple[str, str]:
    buy_pct = training_zones.get("buy_zone_pct", 0.0)
    sell_pct = training_zones.get("sell_zone_pct", 0.0)
    std = training_stats.get("std", 0.0)
    p_range = training_stats.get("max", 0.0) - training_stats.get("min", 0.0)

    if buy_pct < 1.0:
        return "MODEL_DEGENERATED", (
            f"Full dataset_v2 raw inference: buy_zone_pct={buy_pct}% (<1%). "
            f"Model does not produce BUY-zone probabilities on training events."
        )

    collapsed = (
        std < 0.015
        or p_range < 0.08
        or sell_pct > 95.0
        or training_stats.get("max", 1.0) < BUY_ZONE_MIN
    )
    if collapsed:
        return "MODEL_COLLAPSE", (
            f"Probabilities compressed: std={std}, range={p_range:.4f}, "
            f"sell_zone_pct={sell_pct}%, max_p={training_stats.get('max')}."
        )

    if dataset_a_zones is not None:
        a_buy = dataset_a_zones.get("buy_zone_pct", 0.0)
        if buy_pct >= 5.0 and a_buy < 1.0:
            return "MARKET_SPECIFIC", (
                f"Training buy_zone_pct={buy_pct}% but Dataset A buy_zone_pct={a_buy}%."
            )

    return "MODEL_HEALTHY", (
        f"Training buy_zone_pct={buy_pct}%, sell_zone_pct={sell_pct}%, std={std}."
    )


def run_capability_audit(*, base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
    from tradingbot.ml.research.phase22f.config import build_dataset

    bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    ds = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
    if ds is None or ds.empty:
        return {"error": "dataset_v2_missing"}

    weights = extract_model_weights(bundle)
    labels = label_distribution(ds)
    probs, scored_df = raw_predict_all(bundle, ds)
    zones = _zone_counts(probs)
    stats = probability_stats(probs)
    histogram = probability_histogram(probs)

    dataset_a = build_dataset("A")
    ds_a = filter_dataset_a_rows(ds, dataset_a)
    probs_a = np.array([], dtype=float)
    zones_a = None
    stats_a = None
    if not ds_a.empty:
        probs_a, _ = raw_predict_all(bundle, ds_a)
        zones_a = _zone_counts(probs_a)
        stats_a = probability_stats(probs_a)

    verdict, reason = determine_verdict(zones, stats, zones_a)

    return {
        "phase": "22U",
        "production_modified": False,
        "method": (
            "Direct frozen phase9_9 LogisticRegression + StandardScaler on dataset_v2 feature columns; "
            "no TradingKernel, Decision Engine, calibration, or signal thresholds"
        ),
        "model_weights": weights,
        "training_label_distribution": labels,
        "training_probability_distribution": {
            "rows_scored": len(probs),
            "zone_thresholds_for_reporting_only": {
                "buy_zone_min": BUY_ZONE_MIN,
                "sell_zone_max": SELL_ZONE_MAX,
            },
            "zones": zones,
            "statistics": stats,
            "can_produce_buy_on_training": zones.get("buy_zone_pct", 0) >= 1.0,
            "mostly_below_0_45": stats.get("pct_below_0_45", 0) > 50.0,
        },
        "probability_histogram": histogram,
        "dataset_a_subset": {
            "dataset": dataset_a.to_dict(),
            "rows_in_dataset_v2": len(ds_a),
            "zones": zones_a,
            "statistics": stats_a,
        },
        "verdict": verdict,
        "verdict_reason": reason,
    }
