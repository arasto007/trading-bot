"""Phase 14.3 — spread/liquidity quality scoring."""

from __future__ import annotations

SPREAD_NORMAL_MAX = 4.0
SPREAD_MEDIUM_MAX = 8.0


def classify_spread(spread_pips: float) -> str:
    s = float(spread_pips)
    if s < SPREAD_NORMAL_MAX:
        return "normal"
    if s < SPREAD_MEDIUM_MAX:
        return "medium"
    return "high"


def liquidity_quality_score(spread_pips: float) -> tuple[float, str, str]:
    spread_class = classify_spread(spread_pips)
    if spread_class == "normal":
        return 1.0, "spread normal", spread_class
    if spread_class == "medium":
        return 0.7, "spread medium", spread_class
    return 0.0, "spread high — reject", spread_class
