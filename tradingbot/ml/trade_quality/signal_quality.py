"""Phase 14.3 — signal strength scoring from calibrated confidence."""

from __future__ import annotations


def signal_quality_score(confidence: float) -> tuple[float, str]:
    c = float(confidence)
    if c < 0.55:
        return 0.0, "confidence below 0.55"
    if c < 0.65:
        return 0.5, "confidence band 0.55-0.65"
    if c < 0.75:
        return 0.7, "confidence band 0.65-0.75"
    if c < 0.85:
        return 0.85, "confidence band 0.75-0.85"
    return 1.0, "confidence above 0.85"
