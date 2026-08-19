"""Phase 12 — slippage tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SlippageSample:
    requested_price: float
    fill_price: float
    slippage_pips: float
    direction: str


class SlippageTracker:
    def __init__(self) -> None:
        self._samples: list[SlippageSample] = []

    def record(
        self,
        *,
        requested_price: float,
        fill_price: float,
        slippage_pips: float,
        direction: str,
    ) -> None:
        self._samples.append(
            SlippageSample(
                requested_price=requested_price,
                fill_price=fill_price,
                slippage_pips=slippage_pips,
                direction=direction,
            )
        )

    def summary(self) -> dict[str, Any]:
        if not self._samples:
            return {"count": 0, "mean_slippage_pips": 0.0, "max_slippage_pips": 0.0}
        slips = [s.slippage_pips for s in self._samples]
        return {
            "count": len(slips),
            "mean_slippage_pips": round(sum(slips) / len(slips), 4),
            "max_slippage_pips": round(max(slips), 4),
        }
