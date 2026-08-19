"""Shared simulation helpers for shadow policy optimization."""

from __future__ import annotations

from typing import Iterable

import numpy as np

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord, direction_from_decision


DEFAULT_RULE_STRENGTH = 0.80
THRESHOLD_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
ML_WEIGHT_GRID = (0.4, 0.5, 0.6, 0.7, 0.8)


def iter_pairs(
    decisions: list[DecisionRecord],
    outcomes: dict[str, OutcomeRecord],
) -> list[tuple[DecisionRecord, OutcomeRecord]]:
    """Join decisions with outcomes in chronological order (no shuffle)."""
    pairs = [(d, outcomes[d.decision_id]) for d in decisions if d.decision_id in outcomes]
    pairs.sort(key=lambda x: x[0].timestamp)
    return pairs


def rule_strength(record: DecisionRecord) -> float:
    if record.rule_signal.upper() in (DECISION_BUY, DECISION_SELL):
        return DEFAULT_RULE_STRENGTH
    return 0.0


def ml_effective_probability(record: DecisionRecord) -> float:
    direction = record.direction or direction_from_decision(record.hybrid_decision)
    prob = float(record.ml_probability)
    ml_dir = direction_from_decision(record.hybrid_decision)
    if record.rule_signal.upper() in (DECISION_BUY, DECISION_SELL):
        ml_dir = record.rule_signal.upper()
    if direction < 0:
        return prob if ml_dir == DECISION_SELL else (1.0 - prob if ml_dir == DECISION_BUY else prob)
    if direction > 0:
        return prob if ml_dir == DECISION_BUY else (1.0 - prob if ml_dir == DECISION_SELL else prob)
    return prob


def hybrid_score(record: DecisionRecord, *, ml_weight: float, rule_weight: float) -> float:
    ml_part = ml_effective_probability(record)
    rule_part = rule_strength(record)
    if rule_part <= 0:
        return ml_part * ml_weight
    return ml_part * ml_weight + rule_part * rule_weight


def trade_r_values(
    pairs: Iterable[tuple[DecisionRecord, OutcomeRecord]],
    *,
    threshold: float,
    ml_weight: float,
    rule_weight: float,
    min_score: float,
    disabled_sessions: set[str] | None = None,
    disabled_regimes: set[str] | None = None,
) -> list[float]:
    """Simulate which historical shadow trades would be taken under a policy."""
    disabled_sessions = disabled_sessions or set()
    disabled_regimes = disabled_regimes or set()
    r_values: list[float] = []
    for record, outcome in pairs:
        if record.session in disabled_sessions or record.regime in disabled_regimes:
            continue
        if outcome.r_multiple == 0.0:
            continue
        if record.ml_prediction != 1:
            continue
        if record.ml_probability < threshold:
            continue
        score = hybrid_score(record, ml_weight=ml_weight, rule_weight=rule_weight)
        if score < min_score:
            continue
        direction = record.direction or direction_from_decision(record.hybrid_decision)
        if direction == 0 and record.hybrid_decision not in (DECISION_BUY, DECISION_SELL):
            continue
        r_values.append(outcome.r_multiple)
    return r_values


def metrics_from_r(r_values: list[float]) -> dict[str, float]:
    if not r_values:
        return {
            "expected_R": 0.0,
            "win_rate": 0.0,
            "trade_frequency": 0.0,
            "max_drawdown": 0.0,
            "samples": 0.0,
        }
    arr = np.asarray(r_values, dtype=float)
    wins = (arr > 0).sum()
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(equity)
    dd = float((peak - equity).max())
    return {
        "expected_R": round(float(arr.mean()), 4),
        "win_rate": round(float(wins / len(arr)), 4),
        "trade_frequency": float(len(arr)),
        "max_drawdown": round(dd, 4),
        "samples": float(len(arr)),
    }
