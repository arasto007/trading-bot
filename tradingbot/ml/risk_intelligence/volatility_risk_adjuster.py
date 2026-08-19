"""Phase 14.2B — ATR percentile risk adjustment."""

from __future__ import annotations

from tradingbot.ml.risk_intelligence.risk_policy import BLOCK_ATR_PERCENTILE


def volatility_risk_multiplier(atr_percentile: float) -> tuple[float, str, bool]:
    v = float(atr_percentile)
    if v >= BLOCK_ATR_PERCENTILE:
        return 0.0, f"ATR percentile {v:.0f} ≥ {BLOCK_ATR_PERCENTILE} — block", True
    if v < 30.0:
        return 1.10, "LOW volatility +10%", False
    if v <= 70.0:
        return 1.0, "NORMAL volatility", False
    return 0.70, "HIGH volatility -30%", False
