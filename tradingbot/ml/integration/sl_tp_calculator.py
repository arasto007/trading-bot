"""Phase 10.3 — ATR-based SL/TP calculator for virtual shadow trades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.dataset.labels import compute_atr_at, compute_sl_tp
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker


@dataclass
class TradeLevels:
    entry: float
    stop_loss: float
    take_profit: float
    risk_distance: float
    reward_distance: float
    rr_ratio: float
    atr: float
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": round(self.entry, 6),
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "risk_distance": round(self.risk_distance, 6),
            "reward_distance": round(self.reward_distance, 6),
            "rr_ratio": round(self.rr_ratio, 4),
            "atr": round(self.atr, 6),
            "direction": self.direction,
        }


class ATRTradeCalculator:
    """Compute entry/SL/TP from market ATR with fixed 1R:2R."""

    def __init__(
        self,
        *,
        tp_r: float = 2.0,
        sl_r: float = 1.0,
        atr_period: int = 14,
        broker: PaperBroker | None = None,
    ) -> None:
        self.tp_r = tp_r
        self.sl_r = sl_r
        self.atr_period = atr_period
        self._broker = broker or PaperBroker(BrokerConfig(tp_r=tp_r, sl_r=sl_r))

    def compute(
        self,
        candles: pd.DataFrame,
        bar_index: int,
        direction: str,
    ) -> TradeLevels | None:
        """Return trade levels or None when direction is invalid or ATR is zero."""
        upper = direction.upper()
        if upper not in ("BUY", "SELL"):
            return None

        if candles is None or candles.empty or bar_index < 0 or bar_index >= len(candles):
            return None

        close = float(candles.iloc[bar_index]["close"])
        atr = compute_atr_at(candles, bar_index, period=self.atr_period)
        if atr <= 0:
            return None

        dir_int = 1 if upper == "BUY" else -1
        fill = self._broker.execute_entry(close, dir_int)
        sl, tp = compute_sl_tp(fill.fill_price, dir_int, atr, tp_r=self.tp_r, sl_r=self.sl_r)
        risk_distance = abs(fill.fill_price - sl)
        reward_distance = abs(tp - fill.fill_price)
        rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0.0

        return TradeLevels(
            entry=fill.fill_price,
            stop_loss=sl,
            take_profit=tp,
            risk_distance=risk_distance,
            reward_distance=reward_distance,
            rr_ratio=rr_ratio,
            atr=atr,
            direction=upper,
        )
