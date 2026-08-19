"""Confidence engine — map probability to LOW / MEDIUM / HIGH."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceConfig:
    low_min: float = 0.50
    low_max: float = 0.60
    medium_min: float = 0.60
    medium_max: float = 0.70
    high_min: float = 0.70


def confidence_from_probability(probability: float, config: ConfidenceConfig | None = None) -> str:
    """
    Convert win probability to confidence band.

    Default bands:
      0.50–0.60 → LOW
      0.60–0.70 → MEDIUM
      >0.70     → HIGH
    """
    cfg = config or ConfidenceConfig()
    p = float(probability)
    if p >= cfg.high_min:
        return "HIGH"
    if p >= cfg.medium_min:
        return "MEDIUM"
    if p >= cfg.low_min:
        return "LOW"
    return "LOW"
