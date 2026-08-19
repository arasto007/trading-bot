"""Phase 14.2B — calibrated confidence to risk multiplier."""

from __future__ import annotations

from tradingbot.ml.risk_intelligence.risk_policy import MIN_CONFIDENCE_FOR_RISK


def confidence_risk_multiplier(confidence: float) -> tuple[float, str]:
    """
    Map calibrated confidence to risk multiplier.
    Below 0.55 → block (0).
    """
    c = float(confidence)
    if c < MIN_CONFIDENCE_FOR_RISK:
        return 0.0, f"confidence {c:.2f} below {MIN_CONFIDENCE_FOR_RISK} — zero risk"
    if c < 0.65:
        return 0.5, "confidence band 0.55-0.65 ×0.5"
    if c < 0.75:
        return 0.75, "confidence band 0.65-0.75 ×0.75"
    if c < 0.85:
        return 1.0, "confidence band 0.75-0.85 ×1.0"
    return 1.25, "confidence ≥0.85 ×1.25"
