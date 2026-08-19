"""ML / rule weight optimization from shadow history."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.optimization._sim import (
    ML_WEIGHT_GRID,
    iter_pairs,
    metrics_from_r,
    trade_r_values,
)


@dataclass
class WeightCandidate:
    ml_weight: float
    rule_weight: float
    expected_R: float
    win_rate: float
    samples: int
    avg_score: float


@dataclass
class WeightOptimizer:
    """Sweep ML/rule weight combinations on shadow history."""

    ml_weights: tuple[float, ...] = ML_WEIGHT_GRID
    min_samples: int = 5
    threshold: float = 0.50
    min_score: float = 0.60

    def optimize(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> tuple[WeightCandidate | None, list[WeightCandidate], list[str]]:
        pairs = iter_pairs(decisions, outcomes)
        warnings: list[str] = []
        if len(pairs) < self.min_samples:
            warnings.append(f"insufficient samples: {len(pairs)} < {self.min_samples}")

        candidates: list[WeightCandidate] = []
        for ml_w in self.ml_weights:
            rule_w = round(1.0 - ml_w, 4)
            r_vals = trade_r_values(
                pairs,
                threshold=self.threshold,
                ml_weight=ml_w,
                rule_weight=rule_w,
                min_score=self.min_score,
            )
            m = metrics_from_r(r_vals)
            candidates.append(
                WeightCandidate(
                    ml_weight=ml_w,
                    rule_weight=rule_w,
                    expected_R=m["expected_R"],
                    win_rate=m["win_rate"],
                    samples=int(m["samples"]),
                    avg_score=0.0,
                )
            )

        eligible = [c for c in candidates if c.samples >= self.min_samples]
        if not eligible:
            warnings.append("no weight combination met minimum sample requirement")
            best = max(candidates, key=lambda c: (c.samples, c.expected_R)) if candidates else None
            return best, candidates, warnings

        best = max(eligible, key=lambda c: (c.expected_R, c.win_rate))
        return best, candidates, warnings
