"""Causal entry-time feature extraction — no future bars."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.domain.market_filters import atr_percentile, compute_adx


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


def _rsi(closed: pd.DataFrame, period: int = 14) -> float:
    if len(closed) < period + 1:
        return 50.0
    delta = closed["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 100.0
    return float(100 - (100 / (1 + rs))) if not np.isnan(rs) else 50.0


def _atr(closed: pd.DataFrame, period: int = 14) -> float:
    if len(closed) < period + 1:
        return 0.0
    high, low, close = closed["high"], closed["low"], closed["close"]
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return float(val) if not np.isnan(val) else 0.0


def _ema(series: pd.Series, span: int) -> float:
    if len(series) < span:
        return float(series.iloc[-1])
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _market_structure(closed: pd.DataFrame, lookback: int = 20) -> dict[str, float]:
    sub = closed.tail(lookback)
    if len(sub) < 5:
        return {"higher_highs": 0.0, "lower_lows": 0.0, "range_compression": 0.5}
    highs = sub["high"].values
    lows = sub["low"].values
    hh = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1])
    ll = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])
    recent_range = float(sub["high"].max() - sub["low"].min())
    prior = closed.iloc[-(lookback * 2) : -lookback] if len(closed) >= lookback * 2 else sub
    prior_range = float(prior["high"].max() - prior["low"].min()) if len(prior) > 0 else recent_range
    compression = recent_range / prior_range if prior_range > 0 else 1.0
    return {
        "higher_highs": float(hh),
        "lower_lows": float(ll),
        "range_compression": round(compression, 4),
    }


def enrich_trade_at_entry(trade: dict[str, Any], candles: pd.DataFrame) -> dict[str, Any]:
    """Compute causal features using only bars available at entry."""
    ts = pd.Timestamp(trade["timestamp"])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    idx = int(candles.index.searchsorted(ts))
    idx = min(max(idx, 0), len(candles) - 1)
    # Use bars strictly before entry bar (closed only) + entry bar close as forming
    closed = candles.iloc[: idx + 1].copy()
    if len(closed) > 1:
        closed_only = closed.iloc[:-1]  # exclude forming bar for indicators
    else:
        closed_only = closed

    if len(closed_only) < 20:
        closed_only = closed

    entry_price = float(trade.get("entry_price") or trade.get("fill_price") or 0)
    direction = str(trade.get("direction", "BUY"))
    is_buy = direction == "BUY"

    adx = compute_adx(closed_only)
    atr_pct = atr_percentile(closed_only)
    atr = _atr(closed_only)
    rsi = _rsi(closed_only)
    ema20 = _ema(closed_only["close"], 20)
    ema50 = _ema(closed_only["close"], 50)
    ema_dist = (entry_price - ema20) / ema20 * 100 if ema20 > 0 else 0.0
    ema50_dist = (entry_price - ema50) / ema50 * 100 if ema50 > 0 else 0.0
    ema_slope = (ema20 - _ema(closed_only["close"].iloc[:-5], 20)) if len(closed_only) > 25 else 0.0

    vol = closed_only["volume"] if "volume" in closed_only.columns else pd.Series([1.0] * len(closed_only))
    vol_pct = float((vol.tail(50) < vol.iloc[-1]).sum() / max(len(vol.tail(50)) - 1, 1) * 100)

    ms = _market_structure(closed_only)
    dt = ts.to_pydatetime().astimezone(timezone.utc)
    session = _session(dt.hour)

    trend_aligned = (is_buy and ema_slope > 0) or (not is_buy and ema_slope < 0)
    swing_pos = "upper" if entry_price > ema50 else "lower"

    sl = trade.get("sl")
    sl_dist = abs(entry_price - float(sl)) if sl else 0.0
    sl_atr = sl_dist / atr if atr > 0 else 0.0

    return {
        "bar_index": idx,
        "rsi": round(rsi, 4),
        "adx": round(adx, 4),
        "atr": round(atr, 4),
        "atr_percentile": round(atr_pct, 4),
        "spread": float(trade.get("spread") or 0.3),
        "volume_percentile": round(vol_pct, 4),
        "ema20_distance_pct": round(ema_dist, 4),
        "ema50_distance_pct": round(ema50_dist, 4),
        "ema_slope": round(ema_slope, 4),
        "trend_aligned": trend_aligned,
        "market_structure_hh": ms["higher_highs"],
        "market_structure_ll": ms["lower_lows"],
        "range_compression": ms["range_compression"],
        "swing_position": swing_pos,
        "session": session,
        "hour_utc": dt.hour,
        "sl_atr_multiple": round(sl_atr, 4),
        "confidence": float(trade.get("confidence") or 0),
        "regime": str(trade.get("regime") or ""),
        "engine": str(trade.get("engine") or ""),
        "direction": direction,
        "mfe": float(trade.get("mfe") or 0),
        "mae": float(trade.get("mae") or 0),
        "duration_bars": int(trade.get("duration_bars") or 0),
        "pnl": float(trade.get("pnl") or 0),
        "pnl_r": float(trade.get("pnl_r") or 0),
        "is_winner": float(trade.get("pnl") or 0) > 0,
    }
