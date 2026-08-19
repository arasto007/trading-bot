"""Phase 10.3 — virtual trade validation (shadow/paper simulation only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.integration.sl_tp_calculator import TradeLevels


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


class TradeIntegrityValidator:
    """Validate virtual trade geometry, R:R, and position sizing."""

    def __init__(
        self,
        *,
        risk_percent: float = 0.005,
        target_rr: float = 2.0,
        rr_tolerance: float = 0.05,
        min_lot: float = 0.01,
        max_lot: float = 10.0,
        min_stop_distance: float = 1e-6,
    ) -> None:
        self.risk_percent = risk_percent
        self.target_rr = target_rr
        self.rr_tolerance = rr_tolerance
        self.min_lot = min_lot
        self.max_lot = max_lot
        self.min_stop_distance = min_stop_distance

    def validate_trade(
        self,
        *,
        entry: float,
        stop_loss: float,
        take_profit: float,
        direction: str,
        equity: float,
        position_size: float | None = None,
        lot: float | None = None,
        atr: float | None = None,
    ) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        upper = direction.upper()

        if entry <= 0:
            errors.append("invalid entry price")
        if abs(entry - stop_loss) < self.min_stop_distance:
            errors.append("stop_loss equals entry")
        if abs(entry - take_profit) < self.min_stop_distance:
            errors.append("take_profit equals entry")

        risk_distance = abs(entry - stop_loss)
        reward_distance = abs(take_profit - entry)

        if risk_distance <= self.min_stop_distance:
            errors.append("non-positive SL distance")
        if reward_distance <= self.min_stop_distance:
            errors.append("non-positive TP distance")

        if upper == "BUY":
            if not (stop_loss < entry < take_profit):
                errors.append("BUY level ordering invalid (need SL < entry < TP)")
        elif upper == "SELL":
            if not (take_profit < entry < stop_loss):
                errors.append("SELL level ordering invalid (need TP < entry < SL)")
        else:
            errors.append(f"invalid direction: {direction}")

        if risk_distance > 0:
            rr = reward_distance / risk_distance
            if abs(rr - self.target_rr) > self.rr_tolerance:
                errors.append(f"R:R {rr:.4f} != target {self.target_rr}")

        risk_amount = equity * self.risk_percent
        expected_size = risk_amount / risk_distance if risk_distance > self.min_stop_distance else 0.0
        size = position_size if position_size is not None else expected_size
        lot_val = lot if lot is not None else size

        if size <= 0:
            errors.append("position size must be positive")
        if lot_val <= 0:
            errors.append("lot must be positive")
        if lot_val < self.min_lot:
            warnings.append(f"lot {lot_val} below min {self.min_lot}")
        if lot_val > self.max_lot:
            warnings.append(f"lot {lot_val} above max {self.max_lot}")

        if atr is not None and atr <= 0:
            errors.append("ATR must be positive")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def validate_levels(
        self,
        levels: TradeLevels,
        *,
        equity: float,
        lot: float | None = None,
    ) -> ValidationResult:
        return self.validate_trade(
            entry=levels.entry,
            stop_loss=levels.stop_loss,
            take_profit=levels.take_profit,
            direction=levels.direction,
            equity=equity,
            lot=lot,
            atr=levels.atr,
        )

    @staticmethod
    def compute_position_size(equity: float, risk_percent: float, entry: float, stop_loss: float) -> tuple[float, float]:
        """Return (position_size_units, risk_amount)."""
        risk_amount = equity * risk_percent
        stop_distance = abs(entry - stop_loss)
        if stop_distance <= 0:
            return 0.0, risk_amount
        return risk_amount / stop_distance, risk_amount
