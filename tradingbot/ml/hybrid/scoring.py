"""Hybrid scoring — weighted ML + rule contribution."""

from __future__ import annotations

from tradingbot.ml.hybrid.config import HybridConfig
from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL, MLSignal, RuleDirection, RuleSignal


def _ml_effective_probability(ml: MLSignal, target_direction: int) -> float:
    """
    Map ML win probability to the hybrid direction.

    For SELL alignment, invert when ML event direction opposes target.
    """
    prob = float(ml.probability)
    ml_dir = ml.direction.upper()
    if target_direction < 0:
        if ml_dir == DECISION_SELL:
            return prob
        if ml_dir == DECISION_BUY:
            return 1.0 - prob
    elif target_direction > 0:
        if ml_dir == DECISION_BUY:
            return prob
        if ml_dir == DECISION_SELL:
            return 1.0 - prob
    return prob


def compute_final_score(
    rule: RuleSignal | None,
    ml: MLSignal | None,
    *,
    config: HybridConfig,
    resolved_direction: int,
) -> float:
    """
    final_score = ml_probability * ml_weight + rule_strength * rule_weight

    Uses direction-aligned ML probability.
    """
    ml_part = 0.0
    rule_part = 0.0

    if ml is not None and resolved_direction != 0:
        ml_part = _ml_effective_probability(ml, resolved_direction)

    if rule is not None and rule.direction != RuleDirection.NONE:
        rule_part = float(rule.strength)

    if ml is None and rule is None:
        return 0.0
    if ml is None:
        return round(rule_part, 4)
    if rule is None or rule.direction == RuleDirection.NONE:
        return round(ml_part * config.ml_weight / max(config.ml_weight, 1e-9), 4)

    score = ml_part * config.ml_weight + rule_part * config.rule_weight
    return round(max(0.0, min(1.0, score)), 4)
