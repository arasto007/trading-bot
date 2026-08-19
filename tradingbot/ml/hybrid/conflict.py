"""Agreement and conflict resolution between ML and rule signals."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.hybrid.schema import (
    DECISION_BUY,
    DECISION_SELL,
    DECISION_WAIT,
    MLSignal,
    RuleDirection,
    RuleSignal,
)

WARNING_CONFLICT = "ML_RULE_CONFLICT"


@dataclass
class ConflictResult:
    decision: str
    agreement_score: float
    resolved_direction: int
    agreement: bool
    warnings: list[str]


def _ml_direction_int(ml: MLSignal) -> int:
    d = ml.direction.upper()
    if d == DECISION_BUY:
        return int(RuleDirection.BUY)
    if d == DECISION_SELL:
        return int(RuleDirection.SELL)
    return 0


def rule_is_active(rule: RuleSignal | None) -> bool:
    return rule is not None and rule.direction != RuleDirection.NONE


def ml_is_active(ml: MLSignal | None) -> bool:
    if ml is None:
        return False
    return ml.direction.upper() in (DECISION_BUY, DECISION_SELL)


def resolve_conflict(rule: RuleSignal | None, ml: MLSignal | None) -> ConflictResult:
    rule_on = rule_is_active(rule)
    ml_on = ml_is_active(ml)

    if not rule_on and not ml_on:
        return ConflictResult(DECISION_WAIT, 0.0, 0, False, [])

    if rule_on and not ml_on:
        assert rule is not None
        return ConflictResult(
            rule.label,
            0.5,
            rule.direction,
            False,
            [],
        )

    if ml_on and not rule_on:
        assert ml is not None
        d = _ml_direction_int(ml)
        label = DECISION_BUY if d > 0 else DECISION_SELL if d < 0 else DECISION_WAIT
        return ConflictResult(label, 0.5, d, False, [])

    assert rule is not None and ml is not None
    rule_dir = rule.direction
    ml_dir = _ml_direction_int(ml)

    if rule_dir == ml_dir and rule_dir != 0:
        label = DECISION_BUY if rule_dir > 0 else DECISION_SELL
        return ConflictResult(label, 1.0, rule_dir, True, [])

    if rule_dir != 0 and ml_dir != 0 and rule_dir != ml_dir:
        return ConflictResult(DECISION_WAIT, 0.0, 0, False, [WARNING_CONFLICT])

    label = rule.label if rule_dir != 0 else (
        DECISION_BUY if ml_dir > 0 else DECISION_SELL if ml_dir < 0 else DECISION_WAIT
    )
    return ConflictResult(label, 0.5, rule_dir or ml_dir, False, [])
