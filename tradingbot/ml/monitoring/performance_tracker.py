"""Phase 10.4 — extended shadow performance tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class MonitorPerformanceState:
    virtual_entries: int = 0
    closed_trades: int = 0
    holding_bars: list[int] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    hourly_buckets: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record_entry(self) -> None:
        self.virtual_entries += 1

    def record_trade_close(self, trade: dict[str, Any], *, hour_key: str) -> None:
        self.closed_trades += 1
        duration = int(trade.get("duration", 0))
        self.holding_bars.append(duration)
        bucket = self.hourly_buckets.setdefault(
            hour_key,
            {"cycles": 0, "ml_buy": 0, "ml_sell": 0, "ml_hold": 0, "risk_allowed": 0, "trades_closed": 0},
        )
        bucket["trades_closed"] += 1

    def record_equity(self, point: dict[str, Any]) -> None:
        self.equity_curve.append(point)

    def summary(self, metrics: dict[str, Any]) -> dict[str, Any]:
        avg_hold = float(np.mean(self.holding_bars)) if self.holding_bars else 0.0
        return {
            "virtual_entries": self.virtual_entries,
            "closed_trades": self.closed_trades,
            "win_rate": metrics.get("win_rate", 0.0),
            "profit_factor": metrics.get("profit_factor", 0.0),
            "expectancy_r": metrics.get("expectancy_r", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 0.0),
            "max_consecutive_losses": metrics.get("max_consecutive_losses", 0),
            "avg_holding_bars": round(avg_hold, 2),
        }


class PerformanceTracker:
    """Aggregate performance metrics for long shadow runs."""

    def __init__(self) -> None:
        self.state = MonitorPerformanceState()

    def on_virtual_entry(self, hour_key: str) -> None:
        self.state.record_entry()
        bucket = self.state.hourly_buckets.setdefault(
            hour_key,
            {"cycles": 0, "ml_buy": 0, "ml_sell": 0, "ml_hold": 0, "risk_allowed": 0, "trades_closed": 0},
        )
        _ = bucket

    def on_trade_close(self, trade: dict[str, Any], *, hour_key: str) -> None:
        self.state.record_trade_close(trade, hour_key=hour_key)

    def on_equity(self, point: dict[str, Any]) -> None:
        self.state.record_equity(point)

    def hourly_metrics(self) -> list[dict[str, Any]]:
        return [{"hour": k, **v} for k, v in sorted(self.state.hourly_buckets.items())]

    def performance_summary(self, metrics: dict[str, Any]) -> dict[str, Any]:
        return self.state.summary(metrics)
