"""Phase 13.2 — regime-specific feature extraction (research only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

REGIME_FEATURE_COLUMNS: tuple[str, ...] = (
    "adx",
    "atr_percentile",
    "atr_value",
    "ema20_slope",
    "ema50_slope",
    "ema200_distance",
    "volatility",
    "range_pct",
    "trend_strength",
    "higher_high_count",
    "lower_low_count",
    "spread_pips",
)

WARMUP_BARS = 220


def _normalize_candles(candles: pd.DataFrame) -> pd.DataFrame:
    from tradingbot.ml.research.phase13_9.candle_prepare import normalize_candles_index

    return normalize_candles_index(candles)


def _atr_series(df: pd.DataFrame, period: int = 14, *, tr: pd.Series | None = None) -> pd.Series:
    if tr is None:
        from tradingbot.ml.research.phase13_9.candle_prepare import true_range_series

        tr = true_range_series(df)
    return tr.rolling(period, min_periods=period).mean()


def _ema_slope(close: pd.Series, span: int, atr: pd.Series) -> pd.Series:
    ema = close.ewm(span=span, adjust=False).mean()
    raw = ema.diff(5)
    denom = atr.replace(0, np.nan)
    return (raw / denom).fillna(0.0)


def _swing_counts(high: pd.Series, low: pd.Series, window: int = 20) -> tuple[pd.Series, pd.Series]:
    hh = (high == high.rolling(window, min_periods=window).max()).astype(int)
    ll = (low == low.rolling(window, min_periods=window).min()).astype(int)
    return hh.rolling(window).sum(), ll.rolling(window).sum()


def _adx_series(df: pd.DataFrame, period: int = 14, *, tr: pd.Series | None = None) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    if tr is None:
        from tradingbot.ml.research.phase13_9.candle_prepare import true_range_series

        tr = true_range_series(df)
    atr = tr.rolling(period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.rolling(period).mean().fillna(0.0)


def _atr_percentile_series(atr: pd.Series, lookback: int = 252) -> pd.Series:
    def _pct(x: np.ndarray) -> float:
        if len(x) < 2:
            return 50.0
        current = x[-1]
        return float((x[:-1] < current).sum() / (len(x) - 1) * 100)

    return atr.rolling(lookback, min_periods=20).apply(_pct, raw=True).fillna(50.0)


def compute_regime_features_from_candles(
    candles: pd.DataFrame,
    *,
    _normalized: pd.DataFrame | None = None,
    _true_range: pd.Series | None = None,
) -> pd.DataFrame:
    """Bar-level regime features — causal, no look-ahead."""
    df = _normalized if _normalized is not None else _normalize_candles(candles)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    atr = _atr_series(df, tr=_true_range)
    adx = _adx_series(df, tr=_true_range)
    atr_pct = _atr_percentile_series(atr)
    rets = close.pct_change()
    realized_vol = rets.rolling(20, min_periods=5).std() * 100.0
    range_pct = (high - low) / close.replace(0, np.nan) * 100.0
    ema200 = close.ewm(span=200, adjust=False).mean()
    ema200_distance = ((close - ema200) / atr.replace(0, np.nan)).fillna(0.0)
    ema20_slope = _ema_slope(close, 20, atr)
    ema50_slope = _ema_slope(close, 50, atr)
    hh_count, ll_count = _swing_counts(high, low)

    out = pd.DataFrame(
        {
            "timestamp": df.index,
            "adx": adx.round(4),
            "atr_percentile": atr_pct.round(4),
            "atr_value": atr.round(6),
            "ema20_slope": ema20_slope.round(6),
            "ema50_slope": ema50_slope.round(6),
            "ema200_distance": ema200_distance.round(6),
            "volatility": realized_vol.fillna(0.0).round(6),
            "range_pct": range_pct.fillna(0.0).round(6),
            "trend_strength": adx.round(4),
            "higher_high_count": hh_count.fillna(0).astype(int),
            "lower_low_count": ll_count.fillna(0).astype(int),
            "spread_pips": 0.0,
        }
    )
    return out.iloc[WARMUP_BARS:].reset_index(drop=True)


def enrich_from_dataset(dataset: pd.DataFrame) -> pd.DataFrame:
    """Use dataset v2 feature columns when candles unavailable (read-only)."""
    work = dataset.copy()
    if "timestamp" in work.columns:
        work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
        work = work.sort_values("timestamp")

    mapping = {
        "adx": "trend_strength",
        "atr_percentile": "atr_percentile",
        "atr_value": "atr_14",
        "ema50_slope": "ema50_slope",
        "ema200_distance": "ema200_distance",
        "volatility": "realized_vol_20",
        "range_pct": "range_pct",
        "trend_strength": "trend_strength",
        "spread_pips": "spread_pips",
    }
    out = pd.DataFrame({"timestamp": work["timestamp"]})
    for target, source in mapping.items():
        if source in work.columns:
            out[target] = work[source].astype(float).fillna(0.0)
        else:
            out[target] = 0.0

    out["ema20_slope"] = out["ema50_slope"] * 0.5 if "ema50_slope" in out.columns else 0.0
    out["higher_high_count"] = 0
    out["lower_low_count"] = 0
    if "spread_pips" not in work.columns and "spread_zscore" in work.columns:
        out["spread_pips"] = work["spread_zscore"].astype(float).fillna(0.0) * 2.0
    return out.dropna(subset=["timestamp"])
