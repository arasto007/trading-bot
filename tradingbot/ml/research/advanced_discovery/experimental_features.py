"""Phase 9.5 — experimental research-only features (no production pipeline changes)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.features import feature_names

PHASE = "9.5"
EXPERIMENTAL_FEATURE_NAMES: tuple[str, ...] = (
    "atr_expansion_ratio",
    "atr_compression",
    "volatility_breakout",
    "ema_distance_normalized",
    "trend_alignment_score",
    "multi_timeframe_trend_score",
    "candle_strength",
    "rejection_score",
    "momentum_candle_ratio",
    "distance_to_order_block",
    "liquidity_distance",
    "structure_strength",
    "session_volatility_score",
    "session_performance_bias",
)

FORBIDDEN_LEAKAGE_COLUMNS: frozenset[str] = frozenset(
    {
        "label",
        "tp_hit",
        "sl_hit",
        "mfe",
        "mae",
        "future_return",
        "future_window_bars",
    }
)


def _safe_series(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return df[col].astype(float).fillna(default)


def compute_experimental_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive research-only features from point-in-time registry columns.

    Uses only columns available at decision time — no future information.
    """
    out = df.copy()
    atr = _safe_series(out, "atr_14", 1.0).clip(lower=1e-9)
    atr_pct = _safe_series(out, "atr_percentile", 50.0)
    realized = _safe_series(out, "realized_vol_20", 0.0)
    body = _safe_series(out, "body_ratio", 0.0)
    upper_wick = _safe_series(out, "upper_wick_ratio", 0.0)
    lower_wick = _safe_series(out, "lower_wick_ratio", 0.0)
    momentum = _safe_series(out, "momentum_5", 0.0)
    ema200_dist = _safe_series(out, "ema200_distance", 0.0)
    ema50_slope = _safe_series(out, "ema50_slope", 0.0)
    trend_strength = _safe_series(out, "trend_strength", 0.0)
    h4_bias = _safe_series(out, "h4_trend_bias", 0.0)
    h4_struct = _safe_series(out, "h4_structure_direction", 0.0)
    m15_state = _safe_series(out, "m15_market_state", 0.0)
    m5_ctx = _safe_series(out, "m5_entry_context", 0.0)
    ob_dist = _safe_series(out, "order_block_distance", 0.0)
    struct_dist = _safe_series(out, "structure_distance", 0.0)
    liq_sweep = _safe_series(out, "liquidity_sweep", 0.0)
    vol_regime = _safe_series(out, "volatility_regime", 0.0)
    in_london = _safe_series(out, "in_london_kill", 0.0)
    in_ny = _safe_series(out, "in_ny_kill", 0.0)
    in_asia = _safe_series(out, "session_asia", 0.0)
    spread_z = _safe_series(out, "spread_zscore", 0.0)

    out["atr_expansion_ratio"] = (atr / realized.clip(lower=1e-9)).clip(0, 10)
    out["atr_compression"] = (1.0 - (atr_pct / 100.0)).clip(0, 1)
    out["volatility_breakout"] = ((atr_pct > 70) & (realized > realized.median())).astype(float)

    out["ema_distance_normalized"] = (ema200_dist / atr).clip(-5, 5)
    out["trend_alignment_score"] = (h4_bias * h4_struct * np.sign(ema50_slope)).clip(-1, 1)
    out["multi_timeframe_trend_score"] = (
        0.4 * h4_bias + 0.35 * m15_state + 0.25 * np.sign(momentum)
    ).clip(-1, 1)

    out["candle_strength"] = body.clip(0, 1)
    out["rejection_score"] = (upper_wick + lower_wick - body).clip(0, 2)
    out["momentum_candle_ratio"] = (momentum.abs() / body.clip(lower=0.05)).clip(0, 5)

    out["distance_to_order_block"] = ob_dist
    out["liquidity_distance"] = (struct_dist + liq_sweep.abs()).clip(0, 10)
    out["structure_strength"] = (trend_strength / 100.0 + m5_ctx).clip(0, 2)

    out["session_volatility_score"] = (in_london * 0.5 + in_ny * 0.4 + in_asia * 0.1) * vol_regime
    out["session_performance_bias"] = (in_london - in_asia) * spread_z

    return out


def audit_experimental_features(df: pd.DataFrame) -> dict[str, Any]:
    """Leakage audit for experimental feature columns."""
    issues: list[str] = []
    for col in EXPERIMENTAL_FEATURE_NAMES:
        if col in FORBIDDEN_LEAKAGE_COLUMNS:
            issues.append(f"forbidden_column_used:{col}")
        if col in df.columns and df[col].isna().all():
            issues.append(f"all_nan:{col}")
    for forbidden in FORBIDDEN_LEAKAGE_COLUMNS:
        if forbidden in EXPERIMENTAL_FEATURE_NAMES:
            issues.append(f"leakage_name:{forbidden}")
    registry = set(feature_names())
    used_inputs = [c for c in registry if c in df.columns]
    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "experimental_feature_count": len(EXPERIMENTAL_FEATURE_NAMES),
        "registry_inputs_available": len(used_inputs),
    }


def experimental_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Return only experimental feature columns."""
    enriched = compute_experimental_features(df)
    return enriched.loc[:, list(EXPERIMENTAL_FEATURE_NAMES)].astype(np.float64)
