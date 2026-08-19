"""Phase 10.3 — build validated virtual orders from kernel risk approval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.integration.sl_tp_calculator import ATRTradeCalculator
from tradingbot.ml.integration.trade_integrity import TradeIntegrityValidator


@dataclass
class VirtualTradePlan:
    timestamp: str
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    atr: float
    risk_percent: float
    position_size: float
    risk_amount: float
    lot: float
    rr_ratio: float
    validation_status: str

    def to_order_dict(self, *, ml_probability: float | None = None) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry": round(self.entry, 6),
            "size": self.lot,
            "sl": round(self.stop_loss, 6),
            "tp": round(self.take_profit, 6),
            "atr": round(self.atr, 6),
            "risk_percent": self.risk_percent,
            "position_size": round(self.position_size, 6),
            "rr_ratio": round(self.rr_ratio, 4),
            "ml_probability": ml_probability,
            "status": "virtual",
            "validation_status": self.validation_status,
        }

    def to_quality_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry": round(self.entry, 6),
            "sl": round(self.stop_loss, 6),
            "tp": round(self.take_profit, 6),
            "atr": round(self.atr, 6),
            "risk_percent": self.risk_percent,
            "position_size": round(self.position_size, 6),
            "rr_ratio": round(self.rr_ratio, 4),
            "validation_status": self.validation_status,
        }


class VirtualTradeBuilder:
    """ATR-based virtual trade construction with integrity gate."""

    def __init__(
        self,
        *,
        risk_percent: float = 0.005,
        tp_r: float = 2.0,
        sl_r: float = 1.0,
        calculator: ATRTradeCalculator | None = None,
        validator: TradeIntegrityValidator | None = None,
    ) -> None:
        self.risk_percent = risk_percent
        self.calculator = calculator or ATRTradeCalculator(tp_r=tp_r, sl_r=sl_r)
        self.validator = validator or TradeIntegrityValidator(risk_percent=risk_percent, target_rr=tp_r / sl_r)

    def build(
        self,
        *,
        candles: pd.DataFrame,
        bar_index: int,
        direction: str,
        symbol: str,
        timestamp: str,
        equity: float,
        risk_lot: float | None = None,
    ) -> tuple[VirtualTradePlan | None, dict[str, Any] | None]:
        """
        Build a validated virtual trade plan.

        Returns (plan, invalid_record). invalid_record is set when validation fails.
        """
        levels = self.calculator.compute(candles, bar_index, direction)
        if levels is None:
            invalid = {
                "blocked_reason": "atr_or_direction_invalid",
                "timestamp": timestamp,
                "symbol": symbol,
                "direction": direction,
                "entry": None,
                "sl": None,
                "tp": None,
            }
            return None, invalid

        position_size, risk_amount = self.validator.compute_position_size(
            equity, self.risk_percent, levels.entry, levels.stop_loss
        )
        lot = risk_lot if risk_lot and risk_lot > 0 else max(0.01, round(position_size, 2))

        validation = self.validator.validate_levels(levels, equity=equity, lot=lot)
        if not validation.valid:
            invalid = {
                "blocked_reason": "; ".join(validation.errors),
                "timestamp": timestamp,
                "symbol": symbol,
                "direction": direction,
                "entry": round(levels.entry, 6),
                "sl": round(levels.stop_loss, 6),
                "tp": round(levels.take_profit, 6),
                "errors": validation.errors,
                "warnings": validation.warnings,
            }
            return None, invalid

        plan = VirtualTradePlan(
            timestamp=timestamp,
            symbol=symbol,
            direction=levels.direction,
            entry=levels.entry,
            stop_loss=levels.stop_loss,
            take_profit=levels.take_profit,
            atr=levels.atr,
            risk_percent=self.risk_percent,
            position_size=position_size,
            risk_amount=risk_amount,
            lot=lot,
            rr_ratio=levels.rr_ratio,
            validation_status="valid",
        )
        return plan, None
