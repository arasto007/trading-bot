"""Hybrid decision explanations — recommendation only."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.hybrid.conflict import WARNING_CONFLICT
from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL, MLSignal, RuleSignal


def build_explanation(
    *,
    rule: RuleSignal | None,
    ml: MLSignal | None,
    decision: str,
    agreement: bool,
    warnings: list[str],
    features: dict[str, Any] | None = None,
) -> list[str]:
    reasons: list[str] = []
    feats = features or {}

    if ml is not None:
        if ml.confidence == "HIGH":
            reasons.append("ML confidence high")
        elif ml.probability >= 0.65:
            reasons.append(f"ML probability {ml.probability:.2f}")
        if ml.accepted:
            reasons.append("ML policy accepted signal")

    if rule is not None and rule.direction != 0:
        reasons.append(f"Rule signal {rule.label} (strength {rule.strength:.2f})")

    if agreement and rule is not None and ml is not None:
        reasons.append("Rule signal confirms ML direction")

    h4 = feats.get("h4_trend_bias", 0.0)
    if decision == DECISION_BUY and h4 > 0:
        reasons.append("Rule signal confirms H4 bias")
    elif decision == DECISION_SELL and h4 < 0:
        reasons.append("Rule signal confirms H4 bias")

    bos = feats.get("bos_state", 0.0)
    if abs(bos) >= 0.5 and decision in (DECISION_BUY, DECISION_SELL):
        reasons.append("SMC structure supports direction")

    if WARNING_CONFLICT in warnings:
        reasons.append("ML and rules disagree")

    if not rule or rule.direction == 0:
        if ml is not None:
            reasons.append("ML-only signal (no rule input)")
    if ml is None or ml.prediction != 1:
        if rule is not None and rule.direction != 0:
            reasons.append("Rule-only signal (no ML confirmation)")

    if decision in (DECISION_BUY, DECISION_SELL) and agreement:
        reasons.append("ML and rule agreement")

    return reasons
