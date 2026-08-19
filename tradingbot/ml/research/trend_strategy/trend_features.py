"""Phase 13.3 — trend-specific feature extraction (research only)."""

from __future__ import annotations

import numpy as np
import pandas as pd

TREND_FEATURE_COLUMNS: tuple[str, ...] = (
    "ema20",
    "ema50",
    "ema200",
    "ema_alignment",
    "ema20_slope",
    "ema50_slope",
    "adx",
    "atr",
    "atr_percentile",
    "rsi",
    "macd_histogram",
    "higher_high_count",
    "lower_low_count",
    "breakout_distance",
)

WARMUP_BARS = 220


def _normalize(candles: pd.DataFrame) -> pd.DataFrame:
    from tradingbot.ml.research.phase13_9.candle_prepare import normalize_candles_index

    return normalize_candles_index(candles)


def _atr_series(df: pd.DataFrame, period: int = 14, *, tr: pd.Series | None = None) -> pd.Series:
    if tr is None:
        from tradingbot.ml.research.phase13_9.candle_prepare import true_range_series

        tr = true_range_series(df)
    return tr.rolling(period, min_periods=period).mean()


def _adx_series(df: pd.DataFrame, period: int = 14, *, tr: pd.Series | None = None) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
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
        return float((x[:-1] < x[-1]).sum() / (len(x) - 1) * 100)

    return atr.rolling(lookback, min_periods=20).apply(_pct, raw=True).fillna(50.0)


def _ema_slope(ema: pd.Series, atr: pd.Series) -> pd.Series:
    return (ema.diff(5) / atr.replace(0, np.nan)).fillna(0.0)


def compute_trend_features(
    candles: pd.DataFrame,
    *,
    _normalized: pd.DataFrame | None = None,
    _true_range: pd.Series | None = None,
) -> pd.DataFrame:
    """Causal bar-level trend features."""
    df = _normalized if _normalized is not None else _normalize(candles)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    atr = _atr_series(df, tr=_true_range)
    adx = _adx_series(df, tr=_true_range)
    atr_pct = _atr_percentile_series(atr)

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).fillna(50.0)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_hist = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()

    hh = (high == high.rolling(20, min_periods=20).max()).astype(int).rolling(20).sum()
    ll = (low == low.rolling(20, min_periods=20).min()).astype(int).rolling(20).sum()

    recent_high = high.rolling(20).max()
    recent_low = low.rolling(20).min()
    breakout_up = (close - recent_high) / atr.replace(0, np.nan)
    breakout_down = (recent_low - close) / atr.replace(0, np.nan)
    breakout_distance = breakout_up.where(close >= recent_high.shift(1), -breakout_down).fillna(0.0)

    alignment = np.where(
        (ema20 > ema50) & (ema50 > ema200),
        1.0,
        np.where((ema20 < ema50) & (ema50 < ema200), -1.0, 0.0),
    )

    out = pd.DataFrame(
        {
            "timestamp": df.index,
            "open": df["open"].astype(float),
            "high": high,
            "low": low,
            "close": close,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "ema_alignment": alignment,
            "ema20_slope": _ema_slope(ema20, atr),
            "ema50_slope": _ema_slope(ema50, atr),
            "adx": adx,
            "atr": atr,
            "atr_percentile": atr_pct,
            "rsi": rsi,
            "macd_histogram": macd_hist,
            "higher_high_count": hh.fillna(0).astype(int),
            "lower_low_count": ll.fillna(0).astype(int),
            "breakout_distance": breakout_distance,
        }
    )
    return out.iloc[WARMUP_BARS:].reset_index(drop=True)
