"""
پیاده‌سازی‌های موقت (stub) برای تست هسته — فاز ۲ با MT5/استراتژی واقعی جایگزین می‌شوند.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import (
    ExecutionResult,
    MarketKey,
    RiskDecision,
    TradingSignal,
)


class StubMarketData:
    async def update_all(self, symbols: list[str], timeframes: list[str]) -> None:
        pass

    def get_ohlcv(self, market: MarketKey, bars: int = 500) -> pd.DataFrame | None:
        rng = np.random.default_rng(42)
        idx = pd.date_range(end=pd.Timestamp.utcnow(), periods=bars, freq="5min")
        close = 1.1 + np.cumsum(rng.normal(0, 0.0002, bars))
        return pd.DataFrame(
            {
                "open": close - 0.0001,
                "high": close + 0.0003,
                "low": close - 0.0003,
                "close": close,
                "volume": rng.integers(100, 1000, bars),
            },
            index=idx,
        )


class StubIndicators:
    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["sma_20"] = out["close"].rolling(20).mean()
        out["rsi"] = 50.0
        out["atr"] = (out["high"] - out["low"]).rolling(14).mean()
        return out.dropna()


class StubStrategies:
    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        last = df["close"].iloc[-1]
        prev = df["close"].iloc[-2]
        direction = (
            SignalDirection.BUY if last > prev else SignalDirection.SELL
        )
        return TradingSignal(
            direction=direction,
            confidence=0.55,
            symbol=market.symbol,
            timeframe=market.timeframe,
            strategy_name="stub",
        )


class StubRisk:
    def evaluate(self, signal: TradingSignal, portfolio_snapshot: dict) -> RiskDecision:
        return RiskDecision(allowed=True, adjusted_lot=0.01)


class StubExecutor:
    def execute(self, signal: TradingSignal, lot: float) -> ExecutionResult:
        return ExecutionResult(success=True, ticket=100001, message="stub order")

    def manage_open_positions(self, market_key: str) -> None:
        pass
