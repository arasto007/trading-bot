"""Phase 9.10 — simulated paper broker (no real orders)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradingbot.ml.dataset.labels import compute_sl_tp


@dataclass
class BrokerConfig:
    spread_points: float = 0.30
    slippage_points: float = 0.10
    commission: float = 0.0
    tp_r: float = 2.0
    sl_r: float = 1.0


@dataclass
class FillResult:
    fill_price: float
    costs: float


class PaperBroker:
    """Spread/slippage entry simulation and bar-based TP/SL resolution."""

    def __init__(self, config: BrokerConfig | None = None) -> None:
        self.config = config or BrokerConfig()

    def execute_entry(self, price: float, direction: int) -> FillResult:
        half = self.config.spread_points / 2.0
        slip = self.config.slippage_points
        if direction > 0:
            fill = price + half + slip
        elif direction < 0:
            fill = price - half - slip
        else:
            fill = price
        return FillResult(fill_price=fill, costs=half + slip + self.config.commission)

    def sl_tp(self, entry: float, direction: int, risk_unit: float) -> tuple[float, float]:
        return compute_sl_tp(entry, direction, risk_unit, tp_r=self.config.tp_r, sl_r=self.config.sl_r)

    def resolve_bar(
        self,
        bar: pd.Series,
        *,
        direction: int,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[str, float] | None:
        """
        Return (result, exit_price) if SL or TP hit on this bar.

        When both levels are touched on the same bar, SL is resolved first (pessimistic /
        conservative bar ordering — no tick data available).
        """
        high = float(bar["high"])
        low = float(bar["low"])
        if direction > 0:
            sl_hit = low <= stop_loss
            tp_hit = high >= take_profit
            if sl_hit and tp_hit:
                return "SL", stop_loss
            if sl_hit:
                return "SL", stop_loss
            if tp_hit:
                return "TP", take_profit
        elif direction < 0:
            sl_hit = high >= stop_loss
            tp_hit = low <= take_profit
            if sl_hit and tp_hit:
                return "SL", stop_loss
            if sl_hit:
                return "SL", stop_loss
            if tp_hit:
                return "TP", take_profit
        return None
