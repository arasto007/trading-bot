"""Normalize rule, ML, and hybrid inputs to [-1, +1] signals."""

from __future__ import annotations

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL, DECISION_WAIT
from tradingbot.ml.orchestrator.schema import OrchestratorSnapshot


def decision_to_signal(decision: str) -> float:
    d = str(decision).upper()
    if d == DECISION_BUY:
        return 1.0
    if d == DECISION_SELL:
        return -1.0
    return 0.0


def ml_signal(snapshot: OrchestratorSnapshot) -> float:
    """Map ML prediction + probability to signed signal."""
    if snapshot.ml_prediction != 1:
        return 0.0
    direction = snapshot.direction
    if direction == 0:
        direction = 1 if snapshot.ml_probability >= 0.5 else -1
    sign = 1.0 if direction >= 0 else -1.0
    prob = max(0.0, min(1.0, snapshot.ml_probability))
    return round(sign * (2.0 * prob - 1.0), 6)


def rule_signal(snapshot: OrchestratorSnapshot) -> float:
    return decision_to_signal(snapshot.rule_signal)


def hybrid_signal(snapshot: OrchestratorSnapshot) -> float:
    """Use hybrid score scaled by direction when aligned."""
    base = decision_to_signal(snapshot.hybrid_decision)
    if base == 0.0:
        return 0.0
    score = max(0.0, min(1.0, snapshot.hybrid_score or snapshot.final_score))
    return round(base * score, 6)


def extract_signals(snapshot: OrchestratorSnapshot) -> dict[str, float]:
    return {
        "ml": ml_signal(snapshot),
        "rule": rule_signal(snapshot),
        "hybrid": hybrid_signal(snapshot),
    }


def signals_agree(signals: dict[str, float], *, tolerance: float = 0.15) -> bool:
    active = [v for v in signals.values() if abs(v) >= tolerance]
    if len(active) < 2:
        return False
    signs = [1 if v > 0 else -1 for v in active]
    return len(set(signs)) == 1
