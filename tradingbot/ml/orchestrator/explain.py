"""Human-readable final decision explanations."""

from __future__ import annotations

from tradingbot.ml.abtest.schema import WINNER_HYBRID, WINNER_RULE
from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL
from tradingbot.ml.orchestrator.schema import FinalDecision, OrchestratorSnapshot, SourceContributions


def build_reasoning(
    snapshot: OrchestratorSnapshot,
    contributions: SourceContributions,
    *,
    action: str,
    confidence: str,
    active_strategy: str,
    regime: str,
    risk_reasons: list[str],
    regime_reasons: list[str],
) -> list[str]:
    reasons: list[str] = []

    if snapshot.ml_prediction == 1:
        direction = "bullish" if contributions.ml_signal > 0 else "bearish"
        reasons.append(f"ML {direction} ({snapshot.ml_probability:.2f})")
    else:
        reasons.append("ML neutral")

    rule = snapshot.rule_signal.upper()
    if rule in (DECISION_BUY, DECISION_SELL):
        reasons.append(f"Rule {rule.lower()}")
    else:
        reasons.append("Rule neutral")

    hybrid = snapshot.hybrid_decision.upper()
    if hybrid in (DECISION_BUY, DECISION_SELL):
        reasons.append(f"Hybrid {hybrid.lower()} (score {snapshot.hybrid_score:.2f})")
        if rule == hybrid:
            reasons.append("Hybrid aligned with rule")
    else:
        reasons.append("Hybrid wait")

    if snapshot.ab_winner == WINNER_HYBRID:
        reasons.append("A/B winner = hybrid")
    elif snapshot.ab_winner == WINNER_RULE:
        reasons.append("A/B winner = rule")
    else:
        reasons.append("A/B winner = tie")

    if snapshot.max_drawdown_r < 10:
        reasons.append("Drawdown low")
    elif snapshot.max_drawdown_r >= 10:
        reasons.append(f"Drawdown elevated ({snapshot.max_drawdown_r:.1f}R)")

    reasons.append(f"Regime = {regime}")
    reasons.extend(regime_reasons)
    reasons.extend(risk_reasons)
    reasons.append(f"Strategy = {active_strategy}")
    reasons.append(f"Confidence = {confidence}")
    reasons.append(f"Ensemble score = {contributions.adjusted_score:+.3f}")
    reasons.append(f"→ FINAL: {action}")
    return reasons


def format_summary(decision: FinalDecision) -> str:
    lines = [f"→ FINAL: {decision.action}"]
    for reason in decision.reasoning:
        if not reason.startswith("→"):
            lines.insert(-1, reason)
    return "\n".join(lines)
