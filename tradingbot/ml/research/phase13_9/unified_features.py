"""Phase 13.9 — unified feature pipeline (single source of truth)."""

from __future__ import annotations

import os

import pandas as pd

from tradingbot.ml.research.phase13_9.candle_prepare import normalize_candles_index, true_range_series
from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP, TREND_PROTECTED_COLUMNS
from tradingbot.ml.research.regime_detector.regime_features import REGIME_FEATURE_COLUMNS, compute_regime_features_from_candles
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels

ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME = "ENABLE_OPTIMIZED_UNIFIED_FRAME"


def optimized_unified_frame_enabled() -> bool:
    return os.environ.get(ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME, "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _build_unified_frame_legacy(candles: pd.DataFrame, dataset: pd.DataFrame | None = None) -> pd.DataFrame:
    base = build_ml_features(candles).copy()
    base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True)

    regime_raw = compute_regime_features_from_candles(candles)
    regime_raw["timestamp"] = pd.to_datetime(regime_raw["timestamp"], utc=True)

    for col in REGIME_FEATURE_COLUMNS:
        if col not in regime_raw.columns:
            continue
        target = col if col not in base.columns else f"regime_{col}"
        merged_vals = base[["timestamp"]].merge(
            regime_raw[["timestamp", col]].rename(columns={col: target}),
            on="timestamp",
            how="left",
        )[target]
        base[target] = merged_vals

    if dataset is not None and not dataset.empty:
        ds_cols = [c for c in PHASE99_FEATURE_MAP if c in dataset.columns]
        if ds_cols:
            feat = dataset[["timestamp", *ds_cols]].copy()
            feat["timestamp"] = pd.to_datetime(feat["timestamp"], utc=True)
            rename = {src: PHASE99_FEATURE_MAP[src] for src in ds_cols}
            feat = feat.rename(columns=rename)
            base = base.merge(feat, on="timestamp", how="left")

    regimes = attach_regime_labels(base)
    base["regime"] = regimes.values
    return base.sort_values("timestamp").reset_index(drop=True)


def _attach_regime_columns_batch(base: pd.DataFrame, regime_raw: pd.DataFrame) -> pd.DataFrame:
    regime_cols = [col for col in REGIME_FEATURE_COLUMNS if col in regime_raw.columns]
    if not regime_cols:
        return base
    merge_frame = regime_raw[["timestamp", *regime_cols]].copy()
    rename = {
        col: col if col not in base.columns else f"regime_{col}"
        for col in regime_cols
    }
    merge_frame = merge_frame.rename(columns=rename)
    return base.merge(merge_frame, on="timestamp", how="left")


def _attach_phase99_columns(base: pd.DataFrame, dataset: pd.DataFrame) -> pd.DataFrame:
    ds_cols = [c for c in PHASE99_FEATURE_MAP if c in dataset.columns]
    if not ds_cols:
        return base
    feat = dataset[["timestamp", *ds_cols]]
    feat = feat.copy()
    feat["timestamp"] = pd.to_datetime(feat["timestamp"], utc=True)
    rename = {src: PHASE99_FEATURE_MAP[src] for src in ds_cols}
    feat = feat.rename(columns=rename)
    return base.merge(feat, on="timestamp", how="left")


def _build_unified_frame_optimized(candles: pd.DataFrame, dataset: pd.DataFrame | None = None) -> pd.DataFrame:
    normalized = normalize_candles_index(candles)
    tr = true_range_series(normalized)

    base = build_ml_features(candles, _normalized=normalized, _true_range=tr)
    base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True)

    regime_raw = compute_regime_features_from_candles(candles, _normalized=normalized, _true_range=tr)
    regime_raw["timestamp"] = pd.to_datetime(regime_raw["timestamp"], utc=True)

    base = _attach_regime_columns_batch(base, regime_raw)

    if dataset is not None and not dataset.empty:
        base = _attach_phase99_columns(base, dataset)

    regimes = attach_regime_labels(base)
    base["regime"] = regimes.values
    return base.sort_values("timestamp").reset_index(drop=True)


def build_unified_frame(candles: pd.DataFrame, dataset: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Single canonical feature matrix for regime, trend rules, trend ML, and range ML.

    - Trend/regime indicators computed once from candles (Phase 13.3 path).
    - Regime-only extras added with ``regime_`` prefix when names collide.
    - Phase 9.9 dataset features stored as ``phase99_*`` — never overwrite trend columns.
    """
    if optimized_unified_frame_enabled():
        return _build_unified_frame_optimized(candles, dataset)
    return _build_unified_frame_legacy(candles, dataset)


def row_for_phase99_range(row: pd.Series) -> pd.Series:
    """Map unified row to Phase 9.9 feature names for range engine (read-only adapter)."""
    out = row.copy()
    for src, dst in PHASE99_FEATURE_MAP.items():
        if dst in out.index:
            val = out[dst]
            if pd.notna(val):
                out[src] = float(val)
    return out


def protected_columns() -> tuple[str, ...]:
    return TREND_PROTECTED_COLUMNS
