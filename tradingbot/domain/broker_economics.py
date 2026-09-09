"""Broker-native symbol economics — single source of truth for notional, sizing, volume."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BrokerEconomics:
    """MT5 symbol_info economics used for notional, sizing, and validation."""

    symbol: str
    point: float
    digits: int
    contract_size: float
    tick_size: float
    tick_value: float
    tick_value_profit: float
    tick_value_loss: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level: int
    freeze_level: int
    filling_mode: int = 0
    trade_mode: int = 0
    trade_exemode: int = 0
    trade_calc_mode: int = 0

    @classmethod
    def from_mapping(cls, symbol: str, data: dict[str, Any]) -> BrokerEconomics:
        return cls(
            symbol=str(symbol),
            point=float(data["point"]),
            digits=int(data["digits"]),
            contract_size=float(data["contract_size"]),
            tick_size=float(data["tick_size"]),
            tick_value=float(data["tick_value"]),
            tick_value_profit=float(data.get("tick_value_profit", data["tick_value"])),
            tick_value_loss=float(data.get("tick_value_loss", data["tick_value"])),
            volume_min=float(data["volume_min"]),
            volume_max=float(data["volume_max"]),
            volume_step=float(data["volume_step"]),
            stops_level=int(data.get("stops_level", 0)),
            freeze_level=int(data.get("freeze_level", 0)),
            filling_mode=int(data.get("filling_mode", 0)),
            trade_mode=int(data.get("trade_mode", 0)),
            trade_exemode=int(data.get("trade_exemode", 0)),
            trade_calc_mode=int(data.get("trade_calc_mode", 0)),
        )

    @classmethod
    def from_mt5_symbol_info(cls, info: Any) -> BrokerEconomics | None:
        if info is None:
            return None
        try:
            tick_val = float(info.trade_tick_value)
            return cls(
                symbol=str(info.name),
                point=float(info.point),
                digits=int(info.digits),
                contract_size=float(info.trade_contract_size),
                tick_size=float(info.trade_tick_size),
                tick_value=tick_val,
                tick_value_profit=float(getattr(info, "trade_tick_value_profit", tick_val) or tick_val),
                tick_value_loss=float(getattr(info, "trade_tick_value_loss", tick_val) or tick_val),
                volume_min=float(info.volume_min),
                volume_max=float(info.volume_max),
                volume_step=float(info.volume_step),
                stops_level=int(info.trade_stops_level),
                freeze_level=int(info.trade_freeze_level),
                filling_mode=int(info.filling_mode),
                trade_mode=int(info.trade_mode),
                trade_exemode=int(info.trade_exemode),
                trade_calc_mode=int(info.trade_calc_mode),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    def validate_for_sizing(self) -> tuple[bool, str]:
        if not self.symbol:
            return False, "MISSING_SYMBOL"
        if not math.isfinite(self.point) or self.point <= 0:
            return False, "INVALID_POINT"
        if not math.isfinite(self.contract_size) or self.contract_size <= 0:
            return False, "INVALID_CONTRACT_SIZE"
        if not math.isfinite(self.tick_size) or self.tick_size <= 0:
            return False, "INVALID_TICK_SIZE"
        if not math.isfinite(self.tick_value) or self.tick_value <= 0:
            return False, "INVALID_TICK_VALUE"
        if not math.isfinite(self.volume_min) or self.volume_min <= 0:
            return False, "INVALID_VOLUME_MIN"
        if not math.isfinite(self.volume_max) or self.volume_max <= 0:
            return False, "INVALID_VOLUME_MAX"
        if not math.isfinite(self.volume_step) or self.volume_step <= 0:
            return False, "INVALID_VOLUME_STEP"
        if self.volume_min > self.volume_max:
            return False, "VOLUME_MIN_GT_MAX"
        return True, "ok"

    def order_notional(self, lot: float, price: float) -> float:
        """Notional exposure: volume × price × contract_size (CFD)."""
        if lot <= 0 or price <= 0:
            return 0.0
        return lot * price * self.contract_size

    def monetary_loss_per_lot(self, stop_price_distance: float) -> float | None:
        """Account-currency loss per 1.0 lot for a given price stop distance."""
        if stop_price_distance <= 0 or not math.isfinite(stop_price_distance):
            return None
        ticks = stop_price_distance / self.tick_size
        if not math.isfinite(ticks) or ticks <= 0:
            return None
        tick_val = self.tick_value_loss if self.tick_value_loss > 0 else self.tick_value
        if tick_val <= 0:
            return None
        return ticks * tick_val

    def floor_to_volume_step(self, lot: float) -> float:
        """Round lot DOWN to broker volume step (never upward)."""
        if self.volume_step <= 0:
            return lot
        if lot <= 0:
            return 0.0
        steps = math.floor((lot + 1e-12) / self.volume_step)
        return round(steps * self.volume_step, 8)

    def stops_distance_price(self) -> float:
        """Minimum SL/TP distance in price units from broker stops_level."""
        return float(self.stops_level) * self.point

    def freeze_distance_price(self) -> float:
        return float(self.freeze_level) * self.point


def lot_from_broker_economics(
    equity: float,
    risk_per_trade: float,
    entry_price: float,
    stop_loss: float,
    economics: BrokerEconomics,
    *,
    regime_multiplier: float = 1.0,
) -> tuple[float | None, str | None]:
    """
    Size lot from broker tick economics. Never rounds up beyond the risk budget.

    Returns (lot, None) or (None, rejection_reason).
    """
    ok, reason = economics.validate_for_sizing()
    if not ok:
        return None, reason

    if equity <= 0 or not math.isfinite(equity):
        return None, "INVALID_EQUITY"
    if risk_per_trade <= 0 or not math.isfinite(risk_per_trade):
        return None, "INVALID_RISK_FRACTION"
    if entry_price <= 0 or not math.isfinite(entry_price):
        return None, "INVALID_ENTRY"
    if stop_loss <= 0 or not math.isfinite(stop_loss):
        return None, "INVALID_STOP"

    stop_dist = abs(entry_price - stop_loss)
    if stop_dist <= 0:
        return None, "INVALID_STOP_DISTANCE"

    loss_per_lot = economics.monetary_loss_per_lot(stop_dist)
    if loss_per_lot is None or loss_per_lot <= 0:
        return None, "INVALID_MONETARY_LOSS_PER_LOT"

    risk_money = equity * risk_per_trade * regime_multiplier
    if risk_money <= 0:
        return None, "INVALID_RISK_MONEY"

    raw_lot = risk_money / loss_per_lot
    if not math.isfinite(raw_lot) or raw_lot <= 0:
        return None, "INVALID_RAW_VOLUME"

    stepped = economics.floor_to_volume_step(raw_lot)
    if stepped < economics.volume_min - 1e-12:
        return None, "VOLUME_BELOW_MIN"

    if stepped > economics.volume_max + 1e-12:
        stepped = economics.volume_max

    actual_risk = stepped * loss_per_lot
    if actual_risk > risk_money * 1.0001:
        return None, "VOLUME_RISK_EXCEEDED"

    return round(stepped, 2), None


def validate_sl_tp_vs_stops(
    entry: float,
    sl: float | None,
    tp: float | None,
    *,
    is_buy: bool,
    economics: BrokerEconomics,
) -> tuple[bool, str]:
    """Validate SL/TP distance against broker stops_level (pure, no policy)."""
    min_dist = economics.stops_distance_price()
    if min_dist <= 0:
        return True, "ok"
    if sl is not None and sl > 0:
        sl_dist = abs(entry - sl)
        if sl_dist < min_dist - 1e-12:
            return False, f"SL inside stops_level ({sl_dist:.5f} < {min_dist:.5f})"
    if tp is not None and tp > 0:
        tp_dist = abs(entry - tp)
        if tp_dist < min_dist - 1e-12:
            return False, f"TP inside stops_level ({tp_dist:.5f} < {min_dist:.5f})"
    return True, "ok"
