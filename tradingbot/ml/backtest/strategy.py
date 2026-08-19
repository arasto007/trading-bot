"""Model-to-signal conversion for Phase 8.7 backtesting."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.backtest.state import SignalAction


@dataclass
class StrategyConfig:
    buy_threshold: float = 0.55
    sell_threshold: float = 0.45
    allow_sell: bool = True

    def __post_init__(self) -> None:
        if self.sell_threshold >= self.buy_threshold:
            raise ValueError("sell_threshold must be less than buy_threshold")
        if not 0.0 <= self.sell_threshold <= 1.0 or not 0.0 <= self.buy_threshold <= 1.0:
            raise ValueError("thresholds must be in [0, 1]")


class ThresholdStrategy:
    """Baseline probability thresholds: BUY / SELL / HOLD."""

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()

    def generate_signal(self, probability: float) -> SignalAction:
        if probability > self.config.buy_threshold:
            return SignalAction.BUY
        if self.config.allow_sell and probability < self.config.sell_threshold:
            return SignalAction.SELL
        return SignalAction.HOLD

    def should_trade(self, signal: SignalAction) -> bool:
        if signal == SignalAction.SELL and not self.config.allow_sell:
            return False
        return signal in (SignalAction.BUY, SignalAction.SELL)

    def trade_direction(self, signal: SignalAction, event_direction: int) -> int:
        """Map signal + dataset event direction to executed trade direction."""
        if signal == SignalAction.HOLD:
            return 0
        if signal == SignalAction.BUY:
            return 1 if event_direction >= 0 else -1
        return -1 if event_direction >= 0 else 1
