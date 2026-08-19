"""Hybrid decision configuration — weights and thresholds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HybridConfig:
    """Configurable hybrid scoring — no hardcoded values in engine logic."""

    ml_weight: float = 0.6
    rule_weight: float = 0.4
    min_score: float = 0.60
    high_score_threshold: float = 0.75
    medium_score_threshold: float = 0.60
    single_source_penalty: float = 0.15
    require_agreement_for_high: bool = True

    def __post_init__(self) -> None:
        total = self.ml_weight + self.rule_weight
        if abs(total - 1.0) > 1e-6 and total > 0:
            self.ml_weight = self.ml_weight / total
            self.rule_weight = self.rule_weight / total
