"""Port: تولید سیگنال — جایگزین StrategyManager + MetaController."""

from typing import Protocol

import pandas as pd

from tradingbot.domain.models import MarketKey, TradingSignal


class IStrategyRegistry(Protocol):
    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        """ترکیب سیگنال همه استراتژی‌های فعال (معادل generate_combined_signals)."""
        ...
