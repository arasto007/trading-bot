"""Phase 14.2B — regime-based risk adjustment."""

from __future__ import annotations

BLOCKED_REGIMES = frozenset({"NO_TRADE", "HIGH_VOLATILITY"})


def regime_risk_multiplier(regime: str) -> tuple[float, str, bool]:
    """
    Returns (factor, label, blocked).
    NO_TRADE and extreme HIGH_VOL handling may block upstream.
    """
    regime = str(regime).upper()
    if regime == "NO_TRADE":
        return 0.0, "NO_TRADE regime block", True
    if regime == "HIGH_VOLATILITY":
        return 0.5, "HIGH_VOL regime -50%", False
    if regime == "TREND":
        return 1.10, "TREND regime +10%", False
    if regime == "RANGE":
        return 1.0, "RANGE regime normal", False
    return 1.0, f"{regime} neutral", False
