"""
آداپتر استراتژی legacy — wrapper روی StrategyManager.

پشتیبانی از هر استراتژی فعال در ACTIVE_STRATEGIES (فعلاً priceaction).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_loader import ensure_legacy_path, load_legacy_config
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.config.strategies import ACTIVE_STRATEGIES
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.domain.signal_helpers import build_trading_signal
from tradingbot.ports.strategies import IStrategyRegistry

logger = logging.getLogger(__name__)


def _primary_strategy_name(loaded: list[str]) -> str:
    enabled = [k for k, v in ACTIVE_STRATEGIES.items() if v]
    if len(enabled) == 1 and enabled[0] in loaded:
        return enabled[0]
    if len(loaded) == 1:
        return loaded[0]
    return "combined"


class LegacyStrategyRegistry(IStrategyRegistry):
    """آداپتر استراتژی — StrategyManager → signal_helpers → TradingSignal."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        ensure_legacy_path()
        from engine.strategy_manager import StrategyManager  # noqa: E402

        self._config = dict(config or load_legacy_config())
        self._config["enabled_strategies"] = dict(ACTIVE_STRATEGIES)
        self._manager = StrategyManager(self._config, enabled_strategies=ACTIVE_STRATEGIES)
        loaded = list(self._manager.strategies.keys())
        self._primary_strategy = _primary_strategy_name(loaded)
        self._min_confidence = float(
            self._config.get("MIN_CONFIDENCE", self._config.get("min_confidence", 0.58))
        )
        logger.info("Strategies loaded: %s (primary=%s)", loaded, self._primary_strategy)

    @property
    def manager(self) -> Any:
        return self._manager

    @property
    def primary_strategy(self) -> str:
        return self._primary_strategy

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        if df is None or df.empty:
            try:
                from tradingbot.services.engine_telemetry import ENGINE_PA, get_engine_telemetry

                get_engine_telemetry().record_rejection(
                    ENGINE_PA, reason="empty_data", symbol=market.symbol, timeframe=market.timeframe
                )
            except Exception:
                pass
            return None

        legacy_tf = to_legacy(market.timeframe)
        broker_symbol = resolve_broker_symbol(market.symbol, self._config)

        signals, strategy_info = self._manager.generate_combined_signals(
            df, broker_symbol, legacy_tf
        )

        signal = build_trading_signal(
            market,
            df,
            signals,
            strategy_info,
            self._config,
            primary_strategy=self._primary_strategy,
            min_confidence_fallback=self._min_confidence,
        )
        try:
            from tradingbot.services.engine_telemetry import ENGINE_PA, get_engine_telemetry

            tel = get_engine_telemetry(self._config.get("BASE_DIR"))
            if signal is not None and signal.direction.name in ("BUY", "SELL"):
                meta = dict(signal.metadata or {})
                tel.record_signal(
                    ENGINE_PA,
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    direction=signal.direction.name,
                    confidence=float(signal.confidence) if signal.confidence else None,
                    strategy_name=signal.strategy_name,
                    bar_timestamp=str(df.index[-1]),
                    extra={
                        "setup_type": meta.get("setup_type", meta.get("setup", "")),
                        "bos_confirmed": bool(meta.get("bos_confirmed", False)),
                        "fvg_confirmed": bool(meta.get("fvg_confirmed", False)),
                        "liquidity_sweep": bool(meta.get("liquidity_sweep", False)),
                        "quality_score": meta.get("quality_score", 0),
                        "session": meta.get("session", ""),
                    },
                )
            else:
                tel.record_rejection(
                    ENGINE_PA,
                    reason="no_signal_or_low_confidence",
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                )
        except Exception:
            pass
        return signal


# سازگاری با importهای قدیمی
PriceActionStrategyRegistry = LegacyStrategyRegistry
