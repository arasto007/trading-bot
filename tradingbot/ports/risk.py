"""Port: گیت ریسک — جایگزین RiskManager.can_trade + exposure + limits."""

from typing import Protocol

from tradingbot.domain.models import RiskDecision, TradingSignal


class IRiskGate(Protocol):
    def evaluate(self, signal: TradingSignal, portfolio_snapshot: dict) -> RiskDecision:
        """آیا معامله مجاز است؟ (Kelly, VaR, drawdown, correlation, ...)"""
        ...
