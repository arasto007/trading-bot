"""Shadow validation — last N shadow trades analysis."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL, DECISION_WAIT
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord


def _signal_label(record: DecisionRecord) -> str:
    return str(record.hybrid_decision or record.rule_signal or DECISION_WAIT).upper()


def _ml_label(record: DecisionRecord) -> str:
    if record.ml_prediction != 1:
        return DECISION_WAIT
    return DECISION_BUY if record.direction >= 0 else DECISION_SELL


def _rule_label(record: DecisionRecord) -> str:
    return str(record.rule_signal).upper()


@dataclass
class ShadowValidationResult:
    validation_score: float = 0.0
    stability_score: float = 0.0
    noise_ratio: float = 0.0
    sample_count: int = 0
    signal_agreement_rate: float = 0.0
    hybrid_ml_agreement: float = 0.0
    rule_hybrid_agreement: float = 0.0

    def to_dict(self) -> dict:
        return {
            "validation_score": self.validation_score,
            "stability_score": self.stability_score,
            "noise_ratio": self.noise_ratio,
            "sample_count": self.sample_count,
            "signal_agreement_rate": self.signal_agreement_rate,
            "hybrid_ml_agreement": self.hybrid_ml_agreement,
            "rule_hybrid_agreement": self.rule_hybrid_agreement,
        }


@dataclass
class ShadowValidator:
    """Validate recent shadow decisions — no future data used."""

    window: int = 1000

    def validate(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord] | None = None,
    ) -> ShadowValidationResult:
        if not decisions:
            return ShadowValidationResult()

        ordered = sorted(decisions, key=lambda d: d.timestamp)[-self.window :]
        outcomes = outcomes or {}

        noise = 0
        hybrid_ml_agree = 0
        rule_hybrid_agree = 0
        all_agree = 0
        score_sum = 0.0
        switch_count = 0
        prev_hybrid = None

        for record in ordered:
            hybrid = _signal_label(record)
            ml = _ml_label(record)
            rule = _rule_label(record)

            labels = {hybrid, ml, rule} - {DECISION_WAIT}
            if len(labels) > 1:
                noise += 1
            if hybrid == ml or hybrid == DECISION_WAIT or ml == DECISION_WAIT:
                hybrid_ml_agree += 1
            if hybrid == rule or hybrid == DECISION_WAIT or rule == DECISION_WAIT:
                rule_hybrid_agree += 1
            if hybrid == ml == rule or (hybrid != DECISION_WAIT and hybrid == ml == rule):
                all_agree += 1

            if prev_hybrid is not None and hybrid != prev_hybrid:
                switch_count += 1
            prev_hybrid = hybrid

            outcome = outcomes.get(record.decision_id)
            if outcome is not None:
                score_sum += 1.0 if outcome.r_multiple > 0 else 0.0 if outcome.r_multiple == 0 else -0.2

        n = len(ordered)
        noise_ratio = round(noise / n, 6)
        hybrid_ml = round(hybrid_ml_agree / n, 6)
        rule_hybrid = round(rule_hybrid_agree / n, 6)
        agreement = round(all_agree / n, 6)
        switch_rate = switch_count / max(n - 1, 1)

        stability = max(0.0, 1.0 - noise_ratio - switch_rate * 0.5)
        validation = max(0.0, min(1.0, (hybrid_ml + rule_hybrid) / 2.0 - noise_ratio * 0.3))
        if outcomes:
            hit_rate = score_sum / max(len([d for d in ordered if d.decision_id in outcomes]), 1)
            validation = (validation + max(0.0, min(1.0, 0.5 + hit_rate * 0.25))) / 2.0

        return ShadowValidationResult(
            validation_score=round(validation, 6),
            stability_score=round(stability, 6),
            noise_ratio=noise_ratio,
            sample_count=n,
            signal_agreement_rate=agreement,
            hybrid_ml_agreement=hybrid_ml,
            rule_hybrid_agreement=rule_hybrid,
        )
