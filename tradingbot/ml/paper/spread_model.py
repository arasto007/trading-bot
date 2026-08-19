"""Spread simulation model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpreadModel:
    """Session-based bid/ask spread in price units."""

    base_spread: float = 0.30
    london_mult: float = 0.8
    ny_mult: float = 0.9
    asia_mult: float = 1.5
    off_hours_mult: float = 2.0

    def spread(self, session: str, *, volatility_regime: float = 0.5) -> float:
        s = session.lower()
        mult = self.off_hours_mult
        if s == "london":
            mult = self.london_mult
        elif s in ("new_york", "ny"):
            mult = self.ny_mult
        elif s == "asia":
            mult = self.asia_mult
        vol_adj = 1.0 + max(0.0, volatility_regime - 0.5)
        return round(self.base_spread * mult * vol_adj, 6)

    def bid_ask(self, mid: float, session: str, *, volatility_regime: float = 0.5) -> tuple[float, float]:
        half = self.spread(session, volatility_regime=volatility_regime) / 2.0
        return round(mid - half, 6), round(mid + half, 6)
