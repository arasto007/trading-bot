"""Rule-based decision explanations from feature families."""

from __future__ import annotations

from typing import Any


def _flag(value: float, positive_when: str = "gt_zero") -> bool | None:
    if positive_when == "gt_zero":
        return value > 0
    if positive_when == "lt_zero":
        return value < 0
    if positive_when == "eq_one":
        return value >= 0.5
    return None


def explain_decision(
    features: dict[str, float],
    *,
    direction: str = "NEUTRAL",
    prediction: int = 0,
) -> dict[str, Any]:
    """
    Generate human-readable explanation from feature families.

    No SHAP — uses interpretable rules on trend, SMC, context, session,
    volatility, and microstructure features.
    """
    positive: list[str] = []
    negative: list[str] = []

    h4_bias = features.get("h4_trend_bias", 0.0)
    if h4_bias > 0:
        positive.append("H4 bullish bias")
    elif h4_bias < 0:
        positive.append("H4 bearish bias")
    else:
        negative.append("H4 range / neutral bias")

    m15 = features.get("m15_market_state", 0.0)
    if direction == "BUY" and m15 > 0:
        positive.append("M15 trend aligned")
    elif direction == "SELL" and m15 < 0:
        positive.append("M15 trend aligned")
    elif abs(m15) < 0.1:
        negative.append("M15 trend unclear")

    bos = features.get("bos_state", 0.0)
    if abs(bos) >= 0.5:
        positive.append("BOS detected")
    choch = features.get("choch_state", 0.0)
    if abs(choch) >= 0.5:
        positive.append("CHoCH structure shift")

    vol_regime = features.get("volatility_regime", 0.5)
    atr_pct = features.get("atr_percentile", 50.0)
    if vol_regime <= 0.25 or atr_pct < 30:
        positive.append("volatility acceptable")
    elif vol_regime >= 0.75 or atr_pct > 80:
        negative.append("elevated volatility")

    spread_spike = features.get("spread_spike", 0.0)
    spread_z = features.get("spread_zscore", 0.0)
    if spread_spike >= 0.5 or spread_z > 2.0:
        negative.append("spread elevated")

    sweep = features.get("liquidity_sweep", 0.0)
    if abs(sweep) >= 0.5:
        positive.append("liquidity sweep present")

    trend_strength = features.get("trend_strength", 0.0)
    if trend_strength >= 25:
        positive.append("strong trend context")

    if features.get("session_london", 0.0) >= 0.5:
        positive.append("London session active")
    if features.get("session_ny", 0.0) >= 0.5:
        positive.append("New York session active")

    signal = direction if prediction == 1 else "HOLD"
    summary = f"{signal} signal" if signal != "HOLD" else "No actionable ML signal"

    return {
        "summary": summary,
        "positive": positive,
        "negative": negative,
    }
