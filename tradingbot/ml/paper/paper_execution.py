"""Phase 11 — paper execution engine (virtual only, no live orders)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.integration.virtual_trade_builder import VirtualTradeBuilder, VirtualTradePlan


@dataclass
class VirtualOrder:
    symbol: str
    direction: str
    entry: float
    sl: float
    tp: float
    risk_percent: float
    position_size: float
    lot: float
    timestamp: str
    atr: float = 0.0
    rr_ratio: float = 2.0
    ml_probability: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry": round(self.entry, 6),
            "sl": round(self.sl, 6),
            "tp": round(self.tp, 6),
            "risk_percent": self.risk_percent,
            "position_size": round(self.position_size, 6),
            "lot": self.lot,
            "timestamp": self.timestamp,
            "atr": round(self.atr, 6),
            "rr_ratio": round(self.rr_ratio, 4),
            "ml_probability": self.ml_probability,
            "status": "virtual",
        }


class PaperExecutionEngine:
    """Build validated virtual orders after RiskGate approval."""

    def __init__(self, *, risk_percent: float = 0.005, tp_r: float = 2.0, sl_r: float = 1.0) -> None:
        self.builder = VirtualTradeBuilder(risk_percent=risk_percent, tp_r=tp_r, sl_r=sl_r)
        self.virtual_executions = 0
        self.rejected_trades = 0
        self.integrity_failures: list[dict[str, Any]] = []

    def create_order(
        self,
        *,
        candles: pd.DataFrame,
        bar_index: int,
        direction: str,
        symbol: str,
        timestamp: str,
        equity: float,
        risk_lot: float | None = None,
        ml_probability: float | None = None,
    ) -> tuple[VirtualOrder | None, dict[str, Any] | None]:
        plan, invalid = self.builder.build(
            candles=candles,
            bar_index=bar_index,
            direction=direction,
            symbol=symbol,
            timestamp=timestamp,
            equity=equity,
            risk_lot=risk_lot,
        )
        if invalid is not None:
            self.rejected_trades += 1
            self.integrity_failures.append(invalid)
            return None, invalid

        assert plan is not None
        self.virtual_executions += 1
        return self._plan_to_order(plan, ml_probability), None

    @staticmethod
    def _plan_to_order(plan: VirtualTradePlan, ml_probability: float | None) -> VirtualOrder:
        return VirtualOrder(
            symbol=plan.symbol,
            direction=plan.direction,
            entry=plan.entry,
            sl=plan.stop_loss,
            tp=plan.take_profit,
            risk_percent=plan.risk_percent,
            position_size=plan.position_size,
            lot=plan.lot,
            timestamp=plan.timestamp,
            atr=plan.atr,
            rr_ratio=plan.rr_ratio,
            ml_probability=ml_probability,
        )
