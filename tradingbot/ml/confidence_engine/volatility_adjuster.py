"""Phase 14.2A — ATR percentile volatility adjustments."""

from __future__ import annotations

from tradingbot.ml.confidence_engine.calibration_types import VolatilityState

VOLATILITY_FACTORS: dict[VolatilityState, float] = {
    "LOW_VOL": 1.08,
    "NORMAL": 1.00,
    "HIGH_VOL": 0.85,
    "EXTREME": 0.0,
}


def classify_volatility(atr_percentile: float) -> VolatilityState:
    v = float(atr_percentile)
    if v >= 95.0:
        return "EXTREME"
    if v >= 75.0:
        return "HIGH_VOL"
    if v <= 30.0:
        return "LOW_VOL"
    return "NORMAL"


class VolatilityAdjuster:
    def factor(self, atr_percentile: float) -> tuple[float, str, VolatilityState]:
        state = classify_volatility(atr_percentile)
        mult = VOLATILITY_FACTORS[state]
        if state == "EXTREME":
            return 0.0, "EXTREME volatility reject", state
        if state == "LOW_VOL":
            return mult, "LOW_VOL positive", state
        if state == "HIGH_VOL":
            return mult, "HIGH_VOL negative", state
        return mult, "normal volatility +0%", state
