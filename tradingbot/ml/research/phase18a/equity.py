"""Phase 18A — shadow equity curves (proxy PnL only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from tradingbot.ml.research.phase17c.metrics import summarize_returns


@dataclass
class ShadowEquityCurve:
    label: str
    returns: list[float] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)
    regimes: list[str] = field(default_factory=list)

    def add(self, ret: float, *, timestamp: str | None = None, regime: str = "") -> None:
        self.returns.append(float(ret))
        self.timestamps.append(timestamp or "")
        self.regimes.append(regime)

    def equity_series(self) -> list[float]:
        if not self.returns:
            return []
        return [round(float(x), 6) for x in np.cumsum(self.returns)]

    def to_dict(self) -> dict[str, Any]:
        equity = self.equity_series()
        metrics = summarize_returns(self.returns)
        return {
            "phase": "18A",
            "label": self.label,
            "points": len(self.returns),
            "returns": [round(r, 6) for r in self.returns],
            "equity": equity,
            "timestamps": self.timestamps,
            "regimes": self.regimes,
            "metrics": metrics,
            "final_equity": equity[-1] if equity else 0.0,
        }
