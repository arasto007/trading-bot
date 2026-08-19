"""Port: اجرای سفارش — جایگزین OrderManager + place_order در TradingBot."""

from typing import Protocol

from tradingbot.domain.models import ExecutionResult, TradingSignal


class IOrderExecutor(Protocol):
    def execute(self, signal: TradingSignal, lot: float) -> ExecutionResult:
        """ارسال سفارش به MT5 یا شبیه‌ساز backtest."""
        ...

    def manage_open_positions(self, market_key: str) -> None:
        """trailing stop, partial TP — معادل check_positions / manage_trailing_stop."""
        ...
