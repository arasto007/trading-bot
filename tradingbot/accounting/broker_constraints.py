"""MT5 broker constraint model for position sizing and margin."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.domain.position_logic import contract_size, pip_size


@dataclass(frozen=True)
class BrokerConstraints:
    symbol: str
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 10.0
    contract_size: float = 100.0
    tick_size: float = 0.01
    tick_value: float = 1.0
    leverage: float = 100.0

    def round_lot(self, lot: float) -> float:
        if self.lot_step <= 0:
            return lot
        steps = round(lot / self.lot_step)
        return round(steps * self.lot_step, 2)

    def clamp_lot(self, lot: float) -> float:
        rounded = self.round_lot(lot)
        return max(self.min_lot, min(rounded, self.max_lot))

    def margin_required(self, lot: float, price: float) -> float:
        return round(lot * self.contract_size * price / self.leverage, 4)

    def dollar_risk(self, lot: float, sl_distance: float) -> float:
        return round(sl_distance * self.contract_size * lot, 4)

    def risk_percent_of(self, dollar_risk: float, equity: float) -> float:
        if equity <= 0:
            return 0.0
        return round(dollar_risk / equity * 100, 4)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "min_lot": self.min_lot,
            "lot_step": self.lot_step,
            "max_lot": self.max_lot,
            "contract_size": self.contract_size,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "leverage": self.leverage,
        }


def constraints_for_symbol(symbol: str, *, leverage: float = 100.0) -> BrokerConstraints:
    sym = symbol.upper()
    cs = contract_size(sym)
    tick = pip_size(sym) if "XAU" in sym or "GOLD" in sym else 0.00001
    tick_val = cs * tick
    return BrokerConstraints(
        symbol=sym,
        contract_size=cs,
        tick_size=tick,
        tick_value=round(tick_val, 4),
        leverage=leverage,
    )
