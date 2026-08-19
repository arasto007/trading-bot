"""Shadow performance analysis — accuracy, R-multiples, breakdowns."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord


@dataclass
class PerformanceSummary:
    predictions: int
    evaluated: int
    prediction_accuracy: float
    win_rate: float
    expected_R: float
    average_R: float
    max_drawdown: float
    by_session: dict[str, dict[str, float]] = field(default_factory=dict)
    by_regime: dict[str, dict[str, float]] = field(default_factory=dict)
    by_confidence: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PerformanceAnalyzer:
    """Analyze shadow decision performance with session/regime/confidence splits."""

    def analyze(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> PerformanceSummary:
        pairs = [(d, outcomes[d.decision_id]) for d in decisions if d.decision_id in outcomes]
        evaluated = len(pairs)

        if not pairs:
            return PerformanceSummary(
                predictions=len(decisions),
                evaluated=0,
                prediction_accuracy=0.0,
                win_rate=0.0,
                expected_R=0.0,
                average_R=0.0,
                max_drawdown=0.0,
            )

        resolved = [(d, o) for d, o in pairs if o.label in (0, 1)]
        pred_correct = [
            1 for d, o in resolved if d.ml_prediction == o.label
        ]
        prediction_accuracy = len(pred_correct) / len(resolved) if resolved else 0.0

        trades = [
            (d, o) for d, o in pairs
            if d.hybrid_decision in (DECISION_BUY, DECISION_SELL) and o.r_multiple != 0.0
        ]
        r_values = [o.r_multiple for _, o in trades]
        wins = sum(1 for r in r_values if r > 0)
        win_rate = wins / len(r_values) if r_values else 0.0
        expected_r = float(np.mean(r_values)) if r_values else 0.0
        average_r = expected_r
        max_dd = self._max_drawdown(r_values)

        return PerformanceSummary(
            predictions=len(decisions),
            evaluated=evaluated,
            prediction_accuracy=round(prediction_accuracy, 4),
            win_rate=round(win_rate, 4),
            expected_R=round(expected_r, 4),
            average_R=round(average_r, 4),
            max_drawdown=round(max_dd, 4),
            by_session=self._group_metrics(pairs, lambda d, _: d.session),
            by_regime=self._group_metrics(pairs, lambda d, _: d.regime),
            by_confidence=self._group_metrics(pairs, lambda d, _: d.confidence.upper()),
        )

    def _group_metrics(
        self,
        pairs: list[tuple[DecisionRecord, OutcomeRecord]],
        key_fn,
    ) -> dict[str, dict[str, float]]:
        buckets: dict[str, list[float]] = {}
        wins: dict[str, list[int]] = {}
        for d, o in pairs:
            key = key_fn(d, o) or "unknown"
            if d.hybrid_decision not in (DECISION_BUY, DECISION_SELL):
                continue
            if o.r_multiple == 0.0:
                continue
            buckets.setdefault(key, []).append(o.r_multiple)
            wins.setdefault(key, []).append(1 if o.r_multiple > 0 else 0)

        out: dict[str, dict[str, float]] = {}
        for key, rs in buckets.items():
            out[key] = {
                "trades": float(len(rs)),
                "win_rate": round(sum(wins[key]) / len(rs), 4) if rs else 0.0,
                "expected_R": round(float(np.mean(rs)), 4) if rs else 0.0,
                "average_R": round(float(np.mean(rs)), 4) if rs else 0.0,
            }
        return out

    @staticmethod
    def _max_drawdown(r_values: list[float]) -> float:
        if not r_values:
            return 0.0
        equity = np.cumsum(r_values)
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        return float(dd.max())
