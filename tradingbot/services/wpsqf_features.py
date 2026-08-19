"""Causal entry-time features for WPSQF — production source of truth."""

from __future__ import annotations

from datetime import timezone
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.domain.models import TradingSignal

_LOOKBACK = 280
_ADX_PERIOD = 14
_RSI_PERIOD = 14
_ATR_PERIOD = 14
_ATR_PCT_LOOKBACK = 252


def _session(hour: int) -> str:
    if 0 <= hour < 8:
        return "Asian"
    if 8 <= hour < 13:
        return "London"
    if 13 <= hour < 16:
        return "Overlap"
    if 16 <= hour < 21:
        return "New York"
    return "Asian"


def _rolling_mean(arr: np.ndarray, period: int) -> np.ndarray:
    if len(arr) < period:
        return np.array([], dtype=float)
    csum = np.cumsum(arr, dtype=float)
    csum[period:] = csum[period:] - csum[:-period]
    return csum[period - 1 :] / period


def _true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.empty_like(close)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]
    return np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))


def _fast_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = _ADX_PERIOD) -> float:
    if len(close) < period + 2:
        return 0.0
    up = np.diff(high)
    down = -np.diff(low)
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = _true_range(high[1:], low[1:], close[:-1])
    atr = _rolling_mean(tr, period)
    if atr.size == 0:
        return 0.0
    plus_di = 100.0 * _rolling_mean(plus_dm, period) / np.maximum(atr, 1e-12)
    minus_di = 100.0 * _rolling_mean(minus_dm, period) / np.maximum(atr, 1e-12)
    n = min(len(plus_di), len(minus_di))
    if n == 0:
        return 0.0
    plus_di = plus_di[-n:]
    minus_di = minus_di[-n:]
    dx = np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-12) * 100.0
    adx = _rolling_mean(dx, period)
    return float(adx[-1]) if adx.size else 0.0


def _fast_atr_percentile(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> float:
    if len(close) < 20:
        return 50.0
    tr = _true_range(high, low, close)
    atr = _rolling_mean(tr, _ATR_PERIOD)
    if atr.size == 0:
        return 50.0
    window = atr[-min(_ATR_PCT_LOOKBACK, len(atr)) :]
    current = float(window[-1])
    return float((window < current).sum() / max(len(window) - 1, 1) * 100.0)


def _fast_rsi(close: np.ndarray, period: int = _RSI_PERIOD) -> float:
    if len(close) < period + 1:
        return 50.0
    delta = np.diff(close)
    gain = np.clip(delta, 0, None)
    loss = np.clip(-delta, 0, None)
    avg_gain = gain[-period:].mean()
    avg_loss = loss[-period:].mean()
    if avg_loss <= 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _fast_ema(close: np.ndarray, span: int) -> float:
    if len(close) == 0:
        return 0.0
    alpha = 2.0 / (span + 1.0)
    ema = float(close[0])
    for price in close[1:]:
        ema = alpha * float(price) + (1.0 - alpha) * ema
    return ema


def _market_structure(high: np.ndarray, low: np.ndarray, lookback: int = 20) -> dict[str, float]:
    if len(high) < 5:
        return {"higher_highs": 0.0, "lower_lows": 0.0, "range_compression": 0.5}
    sub_h = high[-lookback:]
    sub_l = low[-lookback:]
    hh = float(np.sum(sub_h[1:] > sub_h[:-1]))
    ll = float(np.sum(sub_l[1:] < sub_l[:-1]))
    recent_range = float(sub_h.max() - sub_l.min())
    if len(high) >= lookback * 2:
        prior_h = high[-(lookback * 2) : -lookback]
        prior_l = low[-(lookback * 2) : -lookback]
        prior_range = float(prior_h.max() - prior_l.min())
    else:
        prior_range = recent_range
    compression = recent_range / prior_range if prior_range > 0 else 1.0
    return {"higher_highs": hh, "lower_lows": ll, "range_compression": round(compression, 4)}


def extract_entry_features(
    signal: TradingSignal,
    closed_ohlcv: pd.DataFrame,
    *,
    entry_price: float | None = None,
    spread: float = 0.3,
) -> dict[str, Any]:
    """Compute causal features from closed bars only (no forming bar in indicators)."""
    if len(closed_ohlcv) > 1:
        closed_only = closed_ohlcv.iloc[:-1]
    else:
        closed_only = closed_ohlcv
    if len(closed_only) < 20:
        closed_only = closed_ohlcv

    window = closed_only.tail(_LOOKBACK)
    high = window["high"].to_numpy(dtype=float, copy=False)
    low = window["low"].to_numpy(dtype=float, copy=False)
    close = window["close"].to_numpy(dtype=float, copy=False)

    entry = entry_price or float(closed_ohlcv["close"].iloc[-1])
    direction = signal.direction.name
    is_buy = direction == "BUY"
    meta = signal.metadata or {}

    adx = _fast_adx(high, low, close)
    atr_pct = _fast_atr_percentile(high, low, close)
    tr = _true_range(high, low, close)
    atr_arr = _rolling_mean(tr, _ATR_PERIOD)
    atr_val = float(atr_arr[-1]) if atr_arr.size else 0.0
    rsi = _fast_rsi(close)
    ema20 = _fast_ema(close, 20)
    ema_dist = (entry - ema20) / ema20 * 100 if ema20 > 0 else 0.0
    ema_slope = (_fast_ema(close, 20) - _fast_ema(close[:-5], 20)) if len(close) > 25 else 0.0

    if "volume" in window.columns:
        vol = window["volume"].to_numpy(dtype=float, copy=False)
        tail = vol[-50:] if len(vol) >= 50 else vol
        vol_pct = float((tail < tail[-1]).sum() / max(len(tail) - 1, 1) * 100.0)
    else:
        vol_pct = 50.0

    ms = _market_structure(high, low)
    ts = closed_ohlcv.index[-1]
    dt = pd.Timestamp(ts).to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    session = _session(dt.hour)

    trend_aligned = (is_buy and ema_slope > 0) or (not is_buy and ema_slope < 0)
    conf = float(meta.get("confidence", meta.get("ml_probability", signal.confidence)) or 0)

    return {
        "rsi": round(rsi, 4),
        "adx": round(adx, 4),
        "atr": round(atr_val, 4),
        "atr_percentile": round(atr_pct, 4),
        "spread": spread,
        "volume_percentile": round(vol_pct, 4),
        "ema20_distance_pct": round(ema_dist, 4),
        "ema_slope": round(ema_slope, 4),
        "trend_aligned": trend_aligned,
        "market_structure_hh": ms["higher_highs"],
        "market_structure_ll": ms["lower_lows"],
        "range_compression": ms["range_compression"],
        "session": session,
        "hour_utc": dt.hour,
        "confidence": conf,
        "regime": str(meta.get("regime") or "UNKNOWN"),
        "engine": str(meta.get("engine_name") or signal.strategy_name or ""),
        "direction": direction,
    }
