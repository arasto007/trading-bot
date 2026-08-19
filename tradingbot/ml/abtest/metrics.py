"""A/B arm metrics — win rate, expected R, drawdown, frequency."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tradingbot.ml.abtest.schema import ABDecisionRecord


@dataclass
class ArmMetrics:
    expected_R: float
    win_rate: float
    average_R: float
    drawdown: float
    trade_frequency: float
    samples: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "expected_R": self.expected_R,
            "win_rate": self.win_rate,
            "average_R": self.average_R,
            "drawdown": self.drawdown,
            "trade_frequency": self.trade_frequency,
            "samples": self.samples,
        }


def _max_drawdown(r_values: list[float]) -> float:
    if not r_values:
        return 0.0
    equity = np.cumsum(r_values)
    peak = np.maximum.accumulate(equity)
    return round(float((peak - equity).max()), 4)


def compute_arm_metrics(r_values: list[float]) -> ArmMetrics:
    if not r_values:
        return ArmMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0)
    arr = np.asarray(r_values, dtype=float)
    wins = int((arr > 0).sum())
    return ArmMetrics(
        expected_R=round(float(arr.mean()), 4),
        win_rate=round(wins / len(arr), 4),
        average_R=round(float(arr.mean()), 4),
        drawdown=_max_drawdown(list(arr)),
        trade_frequency=float(len(arr)),
        samples=len(arr),
    )


def rule_r_series(records: list[ABDecisionRecord]) -> list[float]:
    return [r.rule_R for r in records if r.rule_R != 0.0]


def hybrid_r_series(records: list[ABDecisionRecord]) -> list[float]:
    return [r.hybrid_R for r in records if r.hybrid_R != 0.0]
