"""Slippage simulation model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SlippageModel:
    """Adjust entry price for session, volatility, and news events."""

    london_bps: float = 0.5
    ny_bps: float = 0.7
    asia_bps: float = 2.5
    default_bps: float = 1.5
    high_vol_mult: float = 1.8
    news_spike_bps: float = 5.0

    def slippage_price(
        self,
        price: float,
        direction: int,
        *,
        session: str = "unknown",
        volatility_regime: float = 0.5,
        news_event: bool = False,
    ) -> tuple[float, float]:
        bps = self.default_bps
        s = session.lower()
        if s == "london":
            bps = self.london_bps
        elif s in ("new_york", "ny"):
            bps = self.ny_bps
        elif s == "asia":
            bps = self.asia_bps
        if volatility_regime >= 0.75:
            bps *= self.high_vol_mult
        if news_event:
            bps = max(bps, self.news_spike_bps)
        slip = price * (bps / 10_000.0)
        if direction > 0:
            return round(price + slip, 6), round(slip, 6)
        if direction < 0:
            return round(price - slip, 6), round(slip, 6)
        return price, 0.0
