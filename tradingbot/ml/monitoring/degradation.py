"""Model degradation detection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.monitoring.schema import DegradationReport, PerformanceState


@dataclass
class DegradationDetector:
    """Detect performance degradation vs baseline shadow history."""

    baseline_fraction: float = 0.5
    drop_warning_pct: float = 0.40
    min_baseline_samples: int = 20
    min_current_samples: int = 20
    max_losing_streak_warning: int = 5

    def analyze(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> DegradationReport:
        pairs = [(d, outcomes[d.decision_id]) for d in decisions if d.decision_id in outcomes]
        pairs.sort(key=lambda x: x[0].timestamp)

        if len(pairs) < self.min_baseline_samples:
            return DegradationReport(
                baseline_R=0.0,
                current_R=0.0,
                drop_percentage=0.0,
                status=PerformanceState.WARNING.value,
                reasons=["insufficient history for baseline"],
            )

        split = max(self.min_baseline_samples, int(len(pairs) * self.baseline_fraction))
        baseline_pairs = pairs[:split]
        current_pairs = pairs[split:] if len(pairs) > split else pairs[-self.min_current_samples :]

        baseline_r = self._expected_r(baseline_pairs)
        current_r = self._expected_r(current_pairs)
        drop_pct = 0.0
        if baseline_r > 0:
            drop_pct = round((baseline_r - current_r) / baseline_r, 4)
        elif baseline_r != 0:
            drop_pct = round(abs(current_r - baseline_r), 4)

        reasons: list[str] = []
        status = PerformanceState.HEALTHY.value

        if current_r < 0:
            status = PerformanceState.DEGRADED.value
            reasons.append("expected_R below zero")

        if drop_pct >= self.drop_warning_pct:
            status = PerformanceState.WARNING.value if current_r >= 0 else PerformanceState.DEGRADED.value
            reasons.append(f"expected_R dropped {drop_pct:.0%} from baseline")

        win_collapse = self._win_rate(current_pairs) < 0.40 and len(current_pairs) >= self.min_current_samples
        if win_collapse:
            status = PerformanceState.DEGRADED.value
            reasons.append("win rate collapse")

        streak = self._max_losing_streak(current_pairs)
        if streak >= self.max_losing_streak_warning:
            if status == PerformanceState.HEALTHY.value:
                status = PerformanceState.WARNING.value
            reasons.append(f"losing streak of {streak}")

        pred_skew = self._prediction_distribution_skew(current_pairs)
        if pred_skew:
            reasons.append("abnormal prediction distribution")

        cal_mismatch = self._confidence_mismatch(current_pairs)
        if cal_mismatch:
            if status == PerformanceState.HEALTHY.value:
                status = PerformanceState.WARNING.value
            reasons.append("confidence mismatch vs outcomes")

        if not reasons:
            reasons.append("performance within baseline tolerance")

        return DegradationReport(
            baseline_R=round(baseline_r, 4),
            current_R=round(current_r, 4),
            drop_percentage=drop_pct,
            status=status,
            reasons=reasons,
        )

    @staticmethod
    def _expected_r(pairs: list[tuple[DecisionRecord, OutcomeRecord]]) -> float:
        trades = [
            o.r_multiple
            for d, o in pairs
            if d.hybrid_decision in (DECISION_BUY, DECISION_SELL) and o.r_multiple != 0.0
        ]
        return float(np.mean(trades)) if trades else 0.0

    @staticmethod
    def _win_rate(pairs: list[tuple[DecisionRecord, OutcomeRecord]]) -> float:
        trades = [o.r_multiple for _, o in pairs if o.r_multiple != 0.0]
        if not trades:
            return 0.0
        return float(sum(1 for r in trades if r > 0) / len(trades))

    @staticmethod
    def _max_losing_streak(pairs: list[tuple[DecisionRecord, OutcomeRecord]]) -> int:
        streak = 0
        best = 0
        for _, o in pairs:
            if o.r_multiple < 0:
                streak += 1
                best = max(best, streak)
            elif o.r_multiple > 0:
                streak = 0
        return best

    @staticmethod
    def _prediction_distribution_skew(pairs: list[tuple[DecisionRecord, OutcomeRecord]]) -> bool:
        if len(pairs) < 10:
            return False
        preds = [d.ml_prediction for d, _ in pairs]
        pos_rate = sum(preds) / len(preds)
        return pos_rate >= 0.95 or pos_rate <= 0.05

    @staticmethod
    def _confidence_mismatch(pairs: list[tuple[DecisionRecord, OutcomeRecord]]) -> bool:
        high = [(d, o) for d, o in pairs if d.confidence.upper() == "HIGH" and o.label in (0, 1)]
        if len(high) < 5:
            return False
        success = sum(1 for d, o in high if d.ml_prediction == o.label) / len(high)
        return success < 0.55
