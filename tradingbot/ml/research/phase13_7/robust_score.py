"""Phase 13.7 — robust composite scoring with trade-count penalties."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase13_7.config import LOW_TRADE_PENALTY_THRESHOLD
from tradingbot.ml.research.phase13_7.trade_constraints import apply_trade_floor, trade_count


def _norm_pf(pf: float) -> float:
    return min(max(float(pf), 0.0), 3.0) / 3.0


def _norm_expectancy(exp: float) -> float:
    return min(max(float(exp) + 1.0, 0.0), 2.0) / 2.0


def _norm_drawdown(dd: float) -> float:
    return 1.0 - min(max(float(dd), 0.0), 1.0)


def _trade_consistency(trades: int, *, target: int = LOW_TRADE_PENALTY_THRESHOLD) -> float:
    if trades <= 0:
        return 0.0
    return min(trades / target, 1.0)


def low_trade_penalty(trades: int) -> float:
    if trades >= LOW_TRADE_PENALTY_THRESHOLD:
        return 0.0
    if trades <= 0:
        return 1.0
    gap = (LOW_TRADE_PENALTY_THRESHOLD - trades) / LOW_TRADE_PENALTY_THRESHOLD
    return round(min(1.0, gap * 0.5), 4)


def robust_composite_score(
    metrics: dict[str, Any],
    *,
    walk_forward_score: float = 0.5,
    minimum_trades: int = 100,
) -> float:
    """
    robust_score =
      PF 25% + Expectancy 20% + Walk-forward 30% + Trade consistency 15% + Drawdown 10%
    """
    trades = trade_count(metrics)
    pf = _norm_pf(metrics.get("profit_factor", 0.0))
    exp = _norm_expectancy(metrics.get("expectancy", metrics.get("expectancy_r", 0.0)))
    dd = _norm_drawdown(metrics.get("max_drawdown", 1.0))
    wf = min(max(float(walk_forward_score), 0.0), 1.0)
    consistency = _trade_consistency(trades)
    penalty = low_trade_penalty(trades)

    raw = pf * 0.25 + exp * 0.20 + wf * 0.30 + consistency * 0.15 + dd * 0.10
    score = round(max(0.0, raw - penalty), 4)
    return apply_trade_floor(score, metrics, minimum=minimum_trades)


def compare_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda r: r.get("robust_score", 0.0), reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked
