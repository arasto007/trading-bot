"""Phase 9.10 — probability to signal conversion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PaperSignal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class SignalConfig:
    buy_threshold: float = 0.55
    sell_threshold: float = 0.45
    allow_sell: bool = True


class SignalEngine:
    """Map model probability to paper trading signals."""

    def __init__(self, config: SignalConfig | None = None) -> None:
        self.config = config or SignalConfig()
        if self.config.sell_threshold >= self.config.buy_threshold:
            raise ValueError("sell_threshold must be less than buy_threshold")

    def generate(self, probability: float) -> PaperSignal:
        if probability >= self.config.buy_threshold:
            return PaperSignal.BUY
        if self.config.allow_sell and probability <= self.config.sell_threshold:
            return PaperSignal.SELL
        return PaperSignal.HOLD

    def should_trade(self, signal: PaperSignal) -> bool:
        return signal in (PaperSignal.BUY, PaperSignal.SELL)

    def direction(self, signal: PaperSignal) -> int:
        if signal == PaperSignal.BUY:
            return 1
        if signal == PaperSignal.SELL:
            return -1
        return 0
