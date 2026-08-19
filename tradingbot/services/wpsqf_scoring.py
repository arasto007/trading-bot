"""WPSQF scoring — Phase 29A calibrated weights (deterministic)."""

from __future__ import annotations

from typing import Any

from tradingbot.services.wpsqf_calibration import WINNER_CALIBRATION


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def false_signal_score(f: dict[str, Any]) -> dict[str, Any]:
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

    return {"false_signal_score": round(min(100, score), 2), "flags": flags}


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

    return {"context_score": round(max(0, min(100, ctx_score)), 2)}


def signal_quality_score(f: dict[str, Any], *, calibration: dict[str, float] | None = None) -> float:
    """Winner-population membership score 0-100 — frozen Phase 29A calibration."""
    cal = calibration or WINNER_CALIBRATION
    adx = float(f.get("adx", 0))
    conf = float(f.get("confidence", 0))
    false_s = float(f.get("false_signal_score", 0))
    ctx = float(f.get("context_score", 50))
    aligned = 1.0 if f.get("trend_aligned") else 0.0

    w_adx = cal["adx"]
    w_conf = cal["confidence"]
    w_ctx = cal["context_score"]
    w_trend = cal["trend_aligned_rate"]

    s = 0.0
    s += 25 * min(1, adx / max(w_adx, 1))
    s += 20 * min(1, conf / max(w_conf, 0.01))
    s += 20 * (1 - false_s / 100)
    s += 20 * min(1, ctx / max(w_ctx, 1))
    s += 15 * (1 if aligned >= w_trend else 0.5)
    return round(max(0, min(100, s)), 2)
