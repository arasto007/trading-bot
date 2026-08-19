from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from tradingbot.domain.enums import SignalDirection


@dataclass(frozen=True)
class MarketKey:
    """شناسه یک بازار: symbol + timeframe."""

    symbol: str
    timeframe: str

    def __str__(self) -> str:
        return f"{self.symbol}:{self.timeframe}"


@dataclass
class TradingSignal:
    """سیگنال نهایی پس از ترکیب استراتژی‌ها."""

    direction: SignalDirection
    confidence: float
    symbol: str
    timeframe: str
    strategy_name: str = "combined"
    stop_loss: float | None = None
    take_profit: float | None = None
    lot_size: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""
    adjusted_lot: float | None = None


@dataclass
class ExecutionResult:
    success: bool
    ticket: int | None = None
    message: str = ""


@dataclass
class CycleContext:
    """
    زمینه یک چرخه پردازش — داده بین مراحل pipeline منتقل می‌شود.
    معادل state پراکنده در trading_bot.py / system_manager.py قدیم.
    """

    market: MarketKey
    raw_ohlcv: pd.DataFrame | None = None
    enriched_ohlcv: pd.DataFrame | None = None
    signal: TradingSignal | None = None
    risk: RiskDecision | None = None
    execution: ExecutionResult | None = None
    errors: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
