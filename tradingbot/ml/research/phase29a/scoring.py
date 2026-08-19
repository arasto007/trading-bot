"""Trade quality, false signal, and market context scoring."""

from __future__ import annotations

import statistics
from typing import Any


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _scale(val: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return _clamp01((val - lo) / (hi - lo))


def score_components(f: dict[str, Any], *, winner_stats: dict[str, dict[str, float]] | None = None) -> dict[str, float]:
    """Sub-scores 0-100 from causal entry features."""
    conf = float(f.get("confidence") or 0)
    adx = float(f.get("adx") or 0)
    atr_pct = float(f.get("atr_percentile") or 50)
    spread = float(f.get("spread") or 0.3)
    vol_pct = float(f.get("volume_percentile") or 50)
    rsi = float(f.get("rsi") or 50)

    probability = _clamp01(conf) * 100
    trend = _scale(adx, 15, 40) * 100
    if f.get("trend_aligned"):
        trend = min(100, trend * 1.15)

    volatility = 100 - abs(atr_pct - 50) * 1.2
    volatility = max(0, min(100, volatility))

    liquidity = _scale(vol_pct, 20, 80) * 100
    if spread > 0.5:
        liquidity *= 0.7

    session = f.get("session", "Asian")
    session_map = {"Overlap": 90, "New York": 85, "London": 70, "Asian": 60}
    session_q = session_map.get(str(session), 50)

    ms_hh = float(f.get("market_structure_hh") or 0)
    ms_ll = float(f.get("market_structure_ll") or 0)
    is_buy = f.get("direction") == "BUY"
    structure = _scale(ms_hh if is_buy else ms_ll, 5, 15) * 100

    momentum = 100 - abs(rsi - (55 if is_buy else 45)) * 2
    momentum = max(0, min(100, momentum))

    entry = statistics.mean([probability, trend, volatility, liquidity]) 

    return {
        "entry_quality": round(entry, 2),
        "trend_quality": round(trend, 2),
        "volatility_quality": round(volatility, 2),
        "liquidity_quality": round(liquidity, 2),
        "session_quality": round(session_q, 2),
        "market_structure_quality": round(structure, 2),
        "momentum_quality": round(momentum, 2),
        "probability_quality": round(probability, 2),
    }


def composite_quality_score(components: dict[str, float]) -> float:
    weights = {
        "entry_quality": 0.15,
        "trend_quality": 0.15,
        "volatility_quality": 0.10,
        "liquidity_quality": 0.10,
        "session_quality": 0.10,
        "market_structure_quality": 0.15,
        "momentum_quality": 0.10,
        "probability_quality": 0.15,
    }
    total = sum(components.get(k, 0) * w for k, w in weights.items())
    return round(total, 2)


def false_signal_score(f: dict[str, Any]) -> dict[str, Any]:
    """Detect patterns associated with historical losers."""
    flags: list[str] = []
    score = 0.0
    is_buy = f.get("direction") == "BUY"
    rsi = float(f.get("rsi") or 50)
    adx = float(f.get("adx") or 0)
    atr_pct = float(f.get("atr_percentile") or 50)
    conf = float(f.get("confidence") or 0)
    session = str(f.get("session") or "")
    hour = int(f.get("hour_utc") or 12)
    compression = float(f.get("range_compression") or 1.0)
    trend_aligned = bool(f.get("trend_aligned"))
    vol_pct = float(f.get("volume_percentile") or 50)
    ema_dist = abs(float(f.get("ema20_distance_pct") or 0))

    if not trend_aligned:
        flags.append("counter_trend")
        score += 20
    if adx < 18:
        flags.append("weak_trend")
        score += 15
    if is_buy and rsi > 70:
        flags.append("momentum_failure")
        score += 15
    if not is_buy and rsi < 30:
        flags.append("momentum_failure")
        score += 15
    if compression < 0.6:
        flags.append("range_fakeout")
        score += 12
    if atr_pct > 85:
        flags.append("volatility_spike")
        score += 10
    if vol_pct < 25:
        flags.append("low_liquidity")
        score += 12
    if session == "Asian" and 7 <= hour <= 8:
        flags.append("session_transition")
        score += 8
    if ema_dist > 0.15:
        flags.append("late_entry")
        score += 10
    if conf > 0.95 and adx < 20:
        flags.append("weak_breakout")
        score += 15
    if f.get("regime") == "RANGE" and not trend_aligned:
        flags.append("range_fakeout")
        score += 8

    return {
        "false_signal_score": round(min(100, score), 2),
        "flags": flags,
        "flag_count": len(flags),
    }


def market_context_score(f: dict[str, Any]) -> dict[str, Any]:
    adx = float(f.get("adx") or 0)
    atr_pct = float(f.get("atr_percentile") or 50)
    compression = float(f.get("range_compression") or 1.0)
    vol_pct = float(f.get("volume_percentile") or 50)
    session = str(f.get("session") or "Asian")

    if adx >= 30:
        trend_ctx = "strong_trend"
    elif adx >= 18:
        trend_ctx = "weak_trend"
    else:
        trend_ctx = "no_trend"

    if compression < 0.7:
        vol_ctx = "compression"
    elif atr_pct > 75:
        vol_ctx = "expansion"
    elif atr_pct > 90:
        vol_ctx = "volatility_spike"
    else:
        vol_ctx = "normal"

    liq_ctx = "liquidity_vacuum" if vol_pct < 20 else "normal_liquidity"

    ctx_score = 50.0
    if trend_ctx == "strong_trend" and f.get("trend_aligned"):
        ctx_score += 25
    elif trend_ctx == "weak_trend":
        ctx_score += 5
    else:
        ctx_score -= 10
    if vol_ctx == "compression":
        ctx_score -= 5
    elif vol_ctx == "expansion" and f.get("trend_aligned"):
        ctx_score += 10
    if liq_ctx == "liquidity_vacuum":
        ctx_score -= 15
    if session in ("Overlap", "New York"):
        ctx_score += 10

    return {
        "context_score": round(max(0, min(100, ctx_score)), 2),
        "trend_context": trend_ctx,
        "volatility_context": vol_ctx,
        "liquidity_context": liq_ctx,
        "session_context": session,
    }
