"""
Phase 17B — approved Top-5 feature engineering (research only).

All functions are pure, deterministic, and use only past/current bar data.
No look-ahead: every output at index t depends only on rows <= t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row

# Formula documentation for reports.
FORMULAS: dict[str, str] = {
    "adx_acceleration": "adx_t - adx_{t-1}; first difference of ADX (trend strength change).",
    "swing_efficiency": "|close_t - close_{t-L}| / max(atr_t, eps); L=10; displacement per ATR unit.",
    "fractal_dimension_proxy": "sum(|diff(close)|) / (|close_end - close_start| + eps) over rolling window W=30.",
    "trend_age": "consecutive bar count while rule_classify_row(row) == 'TREND'; resets on regime change.",
    "ema_curvature": "ema20_t - 2*ema20_{t-1} + ema20_{t-2}; discrete second derivative of EMA20.",
}


def compute_adx_acceleration(adx: pd.Series) -> pd.Series:
    """adx_acceleration = ADX_t - ADX_{t-1}."""
    return adx.astype(float).diff().fillna(0.0)


def compute_swing_efficiency(close: pd.Series, atr: pd.Series, *, lookback: int = 10) -> pd.Series:
    """|close_t - close_{t-L}| / ATR_t."""
    disp = close.astype(float).diff(lookback).abs()
    denom = atr.astype(float).replace(0, np.nan)
    return (disp / denom).fillna(0.0)


def _fractal_dim_chunk(chunk: np.ndarray) -> float:
    if len(chunk) < 5:
        return 1.0
    path = float(np.sum(np.abs(np.diff(chunk))))
    direct = abs(float(chunk[-1]) - float(chunk[0])) + 1e-12
    return float(np.clip(path / direct, 1.0, 3.0))


def compute_fractal_dimension_proxy(close: pd.Series, *, window: int = 30) -> pd.Series:
    """Path-length / direct-distance ratio on rolling close window."""
    return close.astype(float).rolling(window, min_periods=5).apply(_fractal_dim_chunk, raw=True).fillna(1.0)


def compute_trend_age(regimes: pd.Series | list[str]) -> pd.Series:
    """Consecutive TREND regime bar count; resets when regime != TREND."""
    if isinstance(regimes, pd.Series):
        vals = regimes.astype(str).tolist()
    else:
        vals = list(regimes)
    out: list[int] = []
    age = 0
    for r in vals:
        if r == "TREND":
            age += 1
        else:
            age = 0
        out.append(age)
    return pd.Series(out, index=regimes.index if isinstance(regimes, pd.Series) else None, dtype=float)


def compute_ema_curvature(ema20: pd.Series) -> pd.Series:
    """ema_curvature = ema20_t - 2*ema20_{t-1} + ema20_{t-2}."""
    e = ema20.astype(float)
    return e.diff().diff().fillna(0.0)


def attach_top5_features(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Attach all five approved features to a feature frame (copy).
    Requires: close, atr, adx, ema20; regime labels for trend_age.
    """
    df = frame.copy()
    close = df["close"].astype(float) if "close" in df.columns else pd.Series(0.0, index=df.index)
    atr = df["atr"].astype(float) if "atr" in df.columns else pd.Series(1.0, index=df.index)
    adx = df["adx"].astype(float) if "adx" in df.columns else pd.Series(0.0, index=df.index)
    ema20 = df["ema20"].astype(float) if "ema20" in df.columns else close

    df["adx_acceleration"] = compute_adx_acceleration(adx)
    df["swing_efficiency"] = compute_swing_efficiency(close, atr)
    df["fractal_dimension_proxy"] = compute_fractal_dimension_proxy(close)
    if "regime" in df.columns:
        regimes = df["regime"].astype(str)
    else:
        regimes = pd.Series([rule_classify_row(df.iloc[i]) for i in range(len(df))], index=df.index)
    df["trend_age"] = compute_trend_age(regimes)
    df["ema_curvature"] = compute_ema_curvature(ema20)
    return df


def formulas_report() -> dict:
    return {"features": FORMULAS, "lookback_swing": 10, "window_fractal": 30}
