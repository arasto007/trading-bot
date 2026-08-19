"""Threshold optimization from shadow history."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.optimization._sim import (
    THRESHOLD_GRID,
    iter_pairs,
    metrics_from_r,
    trade_r_values,
)


@dataclass
class ThresholdCandidate:
    threshold: float
    expected_R: float
    win_rate: float
    trade_frequency: float
    max_drawdown: float
    samples: int


@dataclass
class ThresholdOptimizer:
    """Sweep probability thresholds on completed shadow pairs."""

    thresholds: tuple[float, ...] = THRESHOLD_GRID
    min_samples: int = 5
    ml_weight: float = 0.6
    rule_weight: float = 0.4
    min_score: float = 0.60

    def optimize(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> tuple[ThresholdCandidate | None, list[ThresholdCandidate], list[str]]:
        pairs = iter_pairs(decisions, outcomes)
        warnings: list[str] = []
        if len(pairs) < self.min_samples:
            warnings.append(f"insufficient samples: {len(pairs)} < {self.min_samples}")

        candidates: list[ThresholdCandidate] = []
        for thr in self.thresholds:
            r_vals = trade_r_values(
                pairs,
                threshold=thr,
                ml_weight=self.ml_weight,
                rule_weight=self.rule_weight,
                min_score=self.min_score,
            )
            m = metrics_from_r(r_vals)
            candidates.append(
                ThresholdCandidate(
                    threshold=thr,
                    expected_R=m["expected_R"],
                    win_rate=m["win_rate"],
                    trade_frequency=m["trade_frequency"],
                    max_drawdown=m["max_drawdown"],
                    samples=int(m["samples"]),
                )
            )

        eligible = [c for c in candidates if c.samples >= self.min_samples]
        if not eligible:
            warnings.append("no threshold met minimum sample requirement")
            best = max(candidates, key=lambda c: (c.samples, c.expected_R)) if candidates else None
            return best, candidates, warnings

        best = max(eligible, key=lambda c: (c.expected_R, -c.max_drawdown, c.win_rate))
        return best, candidates, warnings
