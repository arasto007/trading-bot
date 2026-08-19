"""Stability checker — regime shifts, strategy switching, confidence distribution."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from tradingbot.ml.deployment.schema import StabilityState
from tradingbot.ml.memory.schema import DecisionRecord, regime_from_features


@dataclass
class StabilityReport:
    stability_state: str = StabilityState.STABLE.value
    regime_shift_count: int = 0
    strategy_switch_rate: float = 0.0
    confidence_entropy: float = 0.0
    inconsistency_rate: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stability_state": self.stability_state,
            "regime_shift_count": self.regime_shift_count,
            "strategy_switch_rate": self.strategy_switch_rate,
            "confidence_entropy": self.confidence_entropy,
            "inconsistency_rate": self.inconsistency_rate,
            "reasons": self.reasons,
        }


@dataclass
class StabilityChecker:
    """Detect unstable shadow behaviour — point-in-time analysis only."""

    regime_shift_threshold: int = 5
    switch_rate_threshold: float = 0.35
    inconsistency_threshold: float = 0.40

    def analyze(self, decisions: list[DecisionRecord]) -> StabilityReport:
        if len(decisions) < 10:
            return StabilityReport(
                stability_state=StabilityState.STABLE.value,
                reasons=["Insufficient samples for stability analysis"],
            )

        ordered = sorted(decisions, key=lambda d: d.timestamp)
        regimes: list[str] = []
        hybrids: list[str] = []
        confidences: list[str] = []
        inconsistent = 0

        prev_regime = None
        regime_shifts = 0
        for record in ordered:
            regime = record.regime if record.regime != "unknown" else regime_from_features(record.features_snapshot)
            regimes.append(regime)
            hybrids.append(str(record.hybrid_decision).upper())
            confidences.append(str(record.confidence).upper())

            if prev_regime is not None and regime != prev_regime:
                regime_shifts += 1
            prev_regime = regime

            if record.ml_prediction == 1 and str(record.rule_signal).upper() != str(record.hybrid_decision).upper():
                if str(record.hybrid_decision).upper() not in ("WAIT", "REJECT"):
                    inconsistent += 1

        switch_count = sum(
            1 for i in range(1, len(hybrids)) if hybrids[i] != hybrids[i - 1]
        )
        switch_rate = switch_count / max(len(hybrids) - 1, 1)
        inconsistency_rate = inconsistent / len(ordered)

        counts = Counter(confidences)
        total = sum(counts.values())
        entropy = 0.0
        for c in counts.values():
            p = c / total
            if p > 0:
                entropy -= p * (p ** 0.5)

        state = StabilityState.STABLE
        reasons: list[str] = []

        if regime_shifts >= self.regime_shift_threshold:
            reasons.append(f"Sudden regime shifts detected ({regime_shifts})")
            state = StabilityState.UNSTABLE

        if switch_rate >= self.switch_rate_threshold:
            reasons.append(f"Frequent strategy switching ({switch_rate:.2%})")
            state = StabilityState.UNSTABLE

        if inconsistency_rate >= self.inconsistency_threshold:
            reasons.append(f"Model inconsistency rate {inconsistency_rate:.2%}")
            state = StabilityState.CRITICAL

        if entropy > 0.55 and switch_rate > 0.25:
            reasons.append("Unstable confidence distribution")
            if state == StabilityState.STABLE:
                state = StabilityState.UNSTABLE

        if not reasons:
            reasons.append("Shadow signals stable")

        return StabilityReport(
            stability_state=state.value,
            regime_shift_count=regime_shifts,
            strategy_switch_rate=round(switch_rate, 6),
            confidence_entropy=round(entropy, 6),
            inconsistency_rate=round(inconsistency_rate, 6),
            reasons=reasons,
        )
