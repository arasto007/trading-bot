"""Simulated broker with spread, slippage, and commission for Phase 8.7."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BrokerConfig:
    spread_points: float = 0.30
    slippage_points: float = 0.10
    commission_per_trade: float = 0.0
    execution_delay_bars: int = 0
    point_value: float = 1.0

    def __post_init__(self) -> None:
        if self.spread_points < 0 or self.slippage_points < 0:
            raise ValueError("spread and slippage must be non-negative")


@dataclass
class FillResult:
    fill_price: float
    costs: float


class SimulatedBroker:
    """Offline execution simulator — no MT5, no live orders."""

    def __init__(self, config: BrokerConfig | None = None) -> None:
        self.config = config or BrokerConfig()

    def execute_entry(self, entry_price: float, direction: int) -> FillResult:
        half_spread = self.config.spread_points / 2.0
        slip = self.config.slippage_points
        if direction > 0:
            fill = entry_price + half_spread + slip
        elif direction < 0:
            fill = entry_price - half_spread - slip
        else:
            fill = entry_price
        spread_cost = (half_spread + slip) * self.config.point_value
        total_cost = spread_cost + self.config.commission_per_trade
        return FillResult(fill_price=fill, costs=total_cost)

    def resolve_exit_price(self, label: int, stop_loss: float, take_profit: float) -> float:
        return take_profit if label == 1 else stop_loss

    def execution_cost_r(self, risk_unit: float, risk_amount: float) -> float:
        """Convert spread/slippage/commission into currency cost relative to risk."""
        if risk_unit <= 0 or risk_amount <= 0:
            return self.config.commission_per_trade
        entry_cost = (self.config.spread_points / 2.0 + self.config.slippage_points) * self.config.point_value
        return entry_cost + self.config.commission_per_trade
