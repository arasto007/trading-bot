"""Phase 14.3 — quality policy and grading."""

from __future__ import annotations

from dataclasses import dataclass

QUALITY_THRESHOLD = 0.65
MIN_RR_RATIO = 2.0

WEIGHTS: dict[str, float] = {
    "signal": 0.30,
    "regime": 0.20,
    "rr": 0.20,
    "volatility": 0.15,
    "liquidity": 0.10,
    "session": 0.05,
}


@dataclass(frozen=True)
class QualityPolicy:
    threshold: float = QUALITY_THRESHOLD
    min_rr: float = MIN_RR_RATIO

    def passes(self, score: float) -> bool:
        return float(score) >= self.threshold


DEFAULT_QUALITY_POLICY = QualityPolicy()


def score_to_grade(score: float) -> str:
    if score >= 0.85:
        return "A"
    if score >= 0.75:
        return "B"
    if score >= 0.65:
        return "C"
    return "D"
