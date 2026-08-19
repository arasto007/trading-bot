"""Rule engine adapter — neutral signal format (no TradingKernel import)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.hybrid.schema import RuleDirection, RuleSignal

_DIRECTION_MAP = {
    "BUY": RuleDirection.BUY,
    "LONG": RuleDirection.BUY,
    "SELL": RuleDirection.SELL,
    "SHORT": RuleDirection.SELL,
    "WAIT": RuleDirection.NONE,
    "NONE": RuleDirection.NONE,
    "HOLD": RuleDirection.NONE,
    "NEUTRAL": RuleDirection.NONE,
}


class RuleAdapter:
    """Convert external rule-based signals into RuleSignal (mock-friendly)."""

    def __init__(self, source: str = "rule_engine") -> None:
        self.source = source

    def from_signal(
        self,
        direction: str | int | None,
        *,
        strength: float = 0.8,
    ) -> RuleSignal:
        if direction is None:
            return self.none()
        if isinstance(direction, int):
            d = direction
            if d > 0:
                key = RuleDirection.BUY
            elif d < 0:
                key = RuleDirection.SELL
            else:
                key = RuleDirection.NONE
            return RuleSignal(direction=int(key), strength=self._clamp(strength), source=self.source)
        label = str(direction).upper().strip()
        mapped = _DIRECTION_MAP.get(label, RuleDirection.NONE)
        return RuleSignal(direction=int(mapped), strength=self._clamp(strength), source=self.source)

    def from_dict(self, payload: dict[str, Any]) -> RuleSignal:
        if "direction" in payload and isinstance(payload["direction"], int):
            return RuleSignal(
                direction=int(payload["direction"]),
                strength=self._clamp(float(payload.get("strength", 0.8))),
                source=str(payload.get("source", self.source)),
            )
        return self.from_signal(
            payload.get("signal") or payload.get("label"),
            strength=float(payload.get("strength", 0.8)),
        )

    def none(self) -> RuleSignal:
        return RuleSignal(direction=int(RuleDirection.NONE), strength=0.0, source=self.source)

    @staticmethod
    def _clamp(value: float) -> float:
        return round(max(0.0, min(1.0, float(value))), 4)
