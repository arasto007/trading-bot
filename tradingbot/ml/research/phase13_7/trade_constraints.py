"""Phase 13.7 — minimum trade count constraints."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase13_7.config import MIN_TRADES_SOFT, MIN_TRADES_STRONG


def trade_count(metrics: dict[str, Any]) -> int:
    return int(metrics.get("trades", 0))


def passes_minimum_trades(metrics: dict[str, Any], *, minimum: int = MIN_TRADES_SOFT) -> bool:
    return trade_count(metrics) >= minimum


def constraint_status(metrics: dict[str, Any]) -> dict[str, Any]:
    trades = trade_count(metrics)
    return {
        "trades": trades,
        "passes_soft_minimum": trades >= MIN_TRADES_SOFT,
        "passes_strong_minimum": trades >= MIN_TRADES_STRONG,
        "rejected": trades < MIN_TRADES_SOFT,
        "strong_reject": trades < MIN_TRADES_STRONG,
        "rejection_reason": (
            None
            if trades >= MIN_TRADES_SOFT
            else f"trades {trades} < minimum {MIN_TRADES_SOFT}"
        ),
    }


def apply_trade_floor(score: float, metrics: dict[str, Any], *, minimum: int = MIN_TRADES_SOFT) -> float:
    """Zero score when trade count is below minimum."""
    if trade_count(metrics) < minimum:
        return 0.0
    return score
