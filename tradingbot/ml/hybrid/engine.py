"""Hybrid decision engine — combines rule + ML signals (shadow only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision.schema import utc_now_iso
from tradingbot.ml.hybrid.config import HybridConfig
from tradingbot.ml.hybrid.conflict import (
    WARNING_CONFLICT,
    ml_is_active,
    resolve_conflict,
    rule_is_active,
)
from tradingbot.ml.hybrid.explain import build_explanation
from tradingbot.ml.hybrid.logger import HybridLogger
from tradingbot.ml.hybrid.ml_adapter import MLAdapter
from tradingbot.ml.hybrid.rules_adapter import RuleAdapter
from tradingbot.ml.hybrid.schema import (
    DECISION_BUY,
    DECISION_REJECT,
    DECISION_SELL,
    DECISION_WAIT,
    HybridDecision,
    RuleSignal,
)
from tradingbot.ml.hybrid.scoring import compute_final_score


def compute_confidence(
    final_score: float,
    agreement_score: float,
    ml_probability: float,
    *,
    config: HybridConfig,
    has_conflict: bool,
    single_source: bool,
) -> str:
    """Map score + agreement to LOW / MEDIUM / HIGH."""
    score = final_score
    if single_source:
        score = max(0.0, score - config.single_source_penalty)
    if has_conflict:
        return "LOW"

    if score >= config.high_score_threshold and agreement_score >= 1.0:
        return "HIGH"
    if score >= config.high_score_threshold and ml_probability >= 0.70:
        return "HIGH"
    if score >= config.medium_score_threshold:
        return "MEDIUM"
    return "LOW"


def _risk_warnings(features: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if float(features.get("spread_spike", 0.0)) >= 0.5:
        warnings.append("spread elevated — risk filter")
    if float(features.get("spread_zscore", 0.0)) > 2.0:
        warnings.append("spread z-score elevated")
    if float(features.get("volatility_regime", 0.5)) >= 0.75:
        warnings.append("high volatility regime")
    return warnings


class HybridDecisionEngine:
    """
    Combine rule-based and ML signals into HybridDecision.

    Recommendation only — never places orders.
    """

    def __init__(
        self,
        ml_adapter: MLAdapter,
        *,
        config: HybridConfig | None = None,
        rule_adapter: RuleAdapter | None = None,
        base_dir: str | Path | None = None,
        log_decisions: bool = True,
    ) -> None:
        self.ml_adapter = ml_adapter
        self.config = config or HybridConfig()
        self.rule_adapter = rule_adapter or RuleAdapter()
        self.base_dir = base_dir
        self.log_decisions = log_decisions
        self._logger = HybridLogger(ml_adapter.predictor.symbol, base_dir)

    def decide(
        self,
        feature_row: dict[str, Any] | pd.Series,
        *,
        rule_signal: str | int | RuleSignal | None = None,
        rule_strength: float = 0.8,
    ) -> HybridDecision:
        data = feature_row.to_dict() if isinstance(feature_row, pd.Series) else dict(feature_row)
        ts = str(data.get("timestamp") or utc_now_iso())
        symbol = str(data.get("symbol") or self.ml_adapter.predictor.symbol)
        timeframe = str(data.get("timeframe") or self.ml_adapter.predictor.timeframe)

        rule: RuleSignal | None
        if isinstance(rule_signal, RuleSignal):
            rule = rule_signal
        elif rule_signal is not None:
            rule = self.rule_adapter.from_signal(rule_signal, strength=rule_strength)
        else:
            rule = None

        ml, _ml_raw = self.ml_adapter.predict_with_raw(data)

        conflict = resolve_conflict(rule, ml)
        warnings = list(conflict.warnings)
        warnings.extend(_risk_warnings(data))

        final_score = compute_final_score(
            rule,
            ml,
            config=self.config,
            resolved_direction=conflict.resolved_direction,
        )

        decision = conflict.decision
        if decision in (DECISION_BUY, DECISION_SELL) and final_score < self.config.min_score:
            decision = DECISION_REJECT
            warnings.append("score below minimum threshold")

        rule_on = rule_is_active(rule)
        ml_on = ml_is_active(ml)
        single_source = (rule_on and not ml_on) or (ml_on and not rule_on)

        confidence = compute_confidence(
            final_score,
            conflict.agreement_score,
            ml.probability,
            config=self.config,
            has_conflict=WARNING_CONFLICT in conflict.warnings,
            single_source=single_source,
        )

        reasons = build_explanation(
            rule=rule,
            ml=ml,
            decision=decision,
            agreement=conflict.agreement,
            warnings=warnings,
            features=data,
        )

        accepted = decision in (DECISION_BUY, DECISION_SELL) and final_score >= self.config.min_score

        hybrid = HybridDecision(
            timestamp=ts,
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            rule_signal=rule.label if rule else "WAIT",
            ml_prediction=ml.prediction,
            ml_probability=ml.probability,
            ml_direction=ml.direction,
            agreement_score=conflict.agreement_score,
            final_score=final_score,
            decision=decision,
            confidence=confidence,
            accepted=accepted,
            reasons=reasons,
            warnings=warnings,
            rule_output=rule.to_dict() if rule else {},
            ml_output=ml.to_dict(),
        )

        if self.log_decisions:
            self._logger.log(hybrid)

        return hybrid
