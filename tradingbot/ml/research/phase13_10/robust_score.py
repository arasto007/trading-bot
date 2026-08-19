"""Phase 13.10 — composite scoring for threshold and router ranking."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase13_10.config import MIN_TRADES_REJECT


def _norm_pf(pf: float) -> float:
    return min(max(float(pf), 0.0), 3.0) / 3.0


def _norm_expectancy(exp: float) -> float:
    return min(max(float(exp) + 1.0, 0.0), 2.0) / 2.0


def _norm_drawdown(dd: float) -> float:
    return 1.0 - min(max(float(dd), 0.0), 1.0)


def _trade_consistency(trades: int, *, target: int = 500) -> float:
    if trades <= 0:
        return 0.0
    return min(trades / target, 1.0)


def threshold_composite_score(
    metrics: dict[str, Any],
    *,
    walk_forward_score: float = 0.5,
    minimum_trades: int = MIN_TRADES_REJECT,
) -> float:
    """
    Score =
      30% Walk Forward + 25% PF + 20% Expectancy + 15% Trade consistency + 10% Drawdown
    """
    trades = int(metrics.get("trades", 0))
    if trades < minimum_trades:
        return 0.0
    wf = min(max(float(walk_forward_score), 0.0), 1.0)
    pf = _norm_pf(metrics.get("profit_factor", 0.0))
    exp = _norm_expectancy(metrics.get("expectancy", metrics.get("expectancy_r", 0.0)))
    dd = _norm_drawdown(metrics.get("max_drawdown", 1.0))
    consistency = _trade_consistency(trades)
    return round(wf * 0.30 + pf * 0.25 + exp * 0.20 + consistency * 0.15 + dd * 0.10, 4)


def count_trend_trades(bt: dict[str, Any] | None) -> int:
    if not bt:
        return 0
    return sum(
        1 for t in bt.get("trades", []) if t.get("type") == "trade" and t.get("source_engine") == "trend_ml"
    )
