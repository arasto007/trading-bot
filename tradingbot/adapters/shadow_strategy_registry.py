"""Phase D — wrap live strategy registry; ML shadow logs only, never trades via ML."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.integration.config import is_ml_shadow_enabled
from tradingbot.ml.shadow.shadow_observer import ShadowObserver
from tradingbot.ports.strategies import IStrategyRegistry

logger = logging.getLogger(__name__)


class ShadowStrategyRegistry(IStrategyRegistry):
    """
    Delegates signal generation to inner registry.
    When ENABLE_ML_SHADOW=true, logs PA/VOL/ML predictions — inner signal only.
    """

    def __init__(
        self,
        inner: IStrategyRegistry,
        legacy_config: dict[str, Any] | None = None,
        *,
        base_dir: str | None = None,
    ) -> None:
        self._inner = inner
        self._engine = type(inner).__name__
        self._observer = ShadowObserver(legacy_config, base_dir=base_dir)
        if is_ml_shadow_enabled():
            logger.info(
                "ShadowStrategyRegistry active | inner=%s | ML predictions log-only",
                self._engine,
            )

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        signal = self._inner.generate_signal(market, df, correlation_data)
        if is_ml_shadow_enabled():
            try:
                self._observer.observe_cycle(
                    market,
                    df,
                    live_signal=signal,
                    inner_engine=self._engine,
                )
                from tradingbot.services.engine_telemetry import ENGINE_ML, get_engine_telemetry

                live_dir = signal.direction.name if signal else "HOLD"
                get_engine_telemetry().record_signal(
                    ENGINE_ML,
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    direction=live_dir,
                    strategy_name="ml_shadow",
                    bar_timestamp=str(df.index[-1]) if df is not None and not df.empty else None,
                    extra={"inner_engine": self._engine, "shadow_mode": True},
                )
            except Exception as exc:
                logger.warning("Shadow observe failed: %s", exc)
        if signal is not None and signal.metadata is not None:
            signal.metadata["ml_shadow_mode"] = True
            signal.metadata["shadow_inner_engine"] = self._engine
        return signal
