"""Simulated broker — spread, slippage, latency, rejection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tradingbot.ml.paper.latency_model import LatencyModel
from tradingbot.ml.paper.slippage_model import SlippageModel
from tradingbot.ml.paper.spread_model import SpreadModel


@dataclass
class BrokerSim:
    """Offline broker simulation — no MT5 connection."""

    spread_model: SpreadModel | None = None
    slippage_model: SlippageModel | None = None
    latency_model: LatencyModel | None = None
    rejection_probability: float = 0.02
    partial_fill_probability: float = 0.05
    deterministic: bool = False
    seed: int = 42

    def __post_init__(self) -> None:
        self.spread_model = self.spread_model or SpreadModel()
        self.slippage_model = self.slippage_model or SlippageModel()
        self.latency_model = self.latency_model or LatencyModel(deterministic=self.deterministic, seed=self.seed)
        self._rng = np.random.default_rng(self.seed if self.deterministic else None)

    def simulate_entry(
        self,
        mid_price: float,
        direction: int,
        *,
        session: str = "unknown",
        volatility_regime: float = 0.5,
        news_event: bool = False,
    ) -> dict:
        if self._rng.random() < self.rejection_probability:
            return {"accepted": False, "reason": "order_rejected"}

        bid, ask = self.spread_model.bid_ask(mid_price, session, volatility_regime=volatility_regime)
        side_price = ask if direction > 0 else bid
        spread_cost = abs(ask - bid)

        adjusted, slippage = self.slippage_model.slippage_price(
            side_price,
            direction,
            session=session,
            volatility_regime=volatility_regime,
            news_event=news_event,
        )
        delay = self.latency_model.delay_bars(self._rng)
        fill_ratio = 1.0
        if self._rng.random() < self.partial_fill_probability:
            fill_ratio = 0.5

        return {
            "accepted": True,
            "entry_price": adjusted,
            "spread_cost": round(spread_cost, 6),
            "slippage": slippage,
            "delay_bars": delay,
            "fill_ratio": fill_ratio,
            "session_liquidity": session,
        }
