"""Phase 14.2A — regime-based calibration adjustments."""

from __future__ import annotations

REGIME_FACTORS: dict[str, float] = {
    "RANGE": 1.10,
    "TREND": 1.15,
    "HIGH_VOLATILITY": 0.50,
    "NO_TRADE": 0.0,
}


class RegimeCalibrator:
    """Apply regime multipliers; NO_TRADE forces zero."""

    def factor(self, regime: str, *, volatility_state: str = "NORMAL") -> tuple[float, str]:
        regime = str(regime).upper()
        base = REGIME_FACTORS.get(regime, 1.0)

        if regime == "NO_TRADE":
            return 0.0, "NO_TRADE force zero"

        if regime == "HIGH_VOLATILITY":
            return base, "HIGH_VOL reduction -50%"

        if regime == "RANGE" and volatility_state == "LOW_VOL":
            boosted = min(base * 1.05, 1.25)
            return round(boosted, 4), "RANGE stable volatility +10%"

        if regime == "RANGE":
            return base, "RANGE factor +10%"

        if regime == "TREND":
            return base, "TREND factor +15%"

        return base, f"{regime} neutral"
