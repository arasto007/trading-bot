"""Phase 13.3 — trend signal builder (research only, no execution)."""

from __future__ import annotations

from typing import Any

import pandas as pd

RISK_PCT = 0.005
RR_RATIO = 2.0
SL_ATR_MULT = 1.0


def build_trend_signal(
    row: pd.Series,
    *,
    symbol: str,
    direction: str,
    confidence: float | None = None,
) -> dict[str, Any]:
    entry = float(row["close"])
    atr = float(row.get("atr", 0.0))
    if atr <= 0:
        atr = max(float(row["high"] - row["low"]), 0.01)

    sl_dist = atr * SL_ATR_MULT
    tp_dist = sl_dist * RR_RATIO

    if direction == "BUY":
        stop_loss = entry - sl_dist
        take_profit = entry + tp_dist
    else:
        stop_loss = entry + sl_dist
        take_profit = entry - tp_dist

    if confidence is None:
        adx = float(row.get("adx", 0))
        slope = abs(float(row.get("ema50_slope", 0)))
        confidence = min(1.0, max(0.35, (adx / 50.0) * 0.5 + slope * 0.5))

    feature_cols = [
        "ema20", "ema50", "ema200", "ema_alignment", "ema50_slope",
        "adx", "atr", "atr_percentile", "rsi", "macd_histogram",
        "higher_high_count", "lower_low_count", "breakout_distance",
    ]
    features = {k: float(row[k]) for k in feature_cols if k in row.index}

    return {
        "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
        "symbol": symbol,
        "direction": direction,
        "confidence": round(confidence, 4),
        "entry": round(entry, 6),
        "stop_loss": round(stop_loss, 6),
        "take_profit": round(take_profit, 6),
        "risk_percent": RISK_PCT,
        "rr_ratio": RR_RATIO,
        "regime": "TREND",
        "features": features,
    }
