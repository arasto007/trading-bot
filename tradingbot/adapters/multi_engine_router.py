"""Phase 46C / 50A — MultiEngineRouter: PA-only production lock or PA → VOL → Adaptive."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from tradingbot.adapters.adaptive_regime_strategy_registry import AdaptiveRegimeStrategyRegistry
from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.adapters.vol_regime_strategy_registry import VolRegimeStrategyRegistry
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ports.strategies import IStrategyRegistry
from tradingbot.services.pa_production_lock import is_pa_production_lock
from tradingbot.services.router_decision_log import record_router_decision

logger = logging.getLogger(__name__)

ENGINE_PA = "PA"
ENGINE_VOL = "VOL_REGIME"
ENGINE_ADAPTIVE = "ADAPTIVE_REGIME"
ENGINE_NONE = "NONE"
PA_STRATEGY_NAME = "priceaction"


def _signal_label(signal: TradingSignal | None) -> str:
    if signal is None:
        return "HOLD"
    name = signal.direction.name
    return name if name in ("BUY", "SELL") else "HOLD"


def _is_valid(signal: TradingSignal | None) -> bool:
    return signal is not None and signal.direction.name in ("BUY", "SELL")


def _normalize_pa_signal(signal: TradingSignal) -> TradingSignal:
    """Ensure production PA identity for meta gate and audit fields."""
    signal.strategy_name = PA_STRATEGY_NAME
    meta = dict(signal.metadata or {})
    meta["selected_engine"] = ENGINE_PA
    meta["router_engine"] = ENGINE_PA
    signal.metadata = meta
    return signal


def _tag_router(signal: TradingSignal, *, engine: str, pa: str, vol: str, adaptive: str) -> TradingSignal:
    meta = dict(signal.metadata or {})
    meta["router_engine"] = engine
    meta["selected_engine"] = engine
    meta["router_pa_signal"] = pa
    meta["router_vol_signal"] = vol
    meta["router_adaptive_signal"] = adaptive
    signal.metadata = meta
    if engine == ENGINE_PA:
        signal.strategy_name = PA_STRATEGY_NAME
    return signal


class MultiEngineRouterRegistry(IStrategyRegistry):
    """
    Phase 50A (PA_PRODUCTION_LOCK): PA only — VOL/Adaptive logged, never selected.
    Legacy: Price Action → VOL_REGIME → Adaptive fallback.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or load_legacy_config())
        self._pa = LegacyStrategyRegistry(self._config)
        self._vol = VolRegimeStrategyRegistry(self._config)
        self._adaptive = AdaptiveRegimeStrategyRegistry(self._config)
        self._pa_only = is_pa_production_lock(self._config)
        if self._pa_only:
            logger.info(
                "MultiEngineRouter PA PRODUCTION LOCK | PA only | vol/adaptive=log-only"
            )
        else:
            logger.info(
                "MultiEngineRouter active | priority=%s > %s > %s",
                ENGINE_PA,
                ENGINE_VOL,
                ENGINE_ADAPTIVE,
            )

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        if df is None or df.empty:
            try:
                from tradingbot.services.live_loop_health import record_router_activity

                record_router_activity(pa_hold=True, selected_engine_none=True)
            except Exception:
                pass
            return None

        ts = str(df.index[-1])
        pa_sig = self._pa.generate_signal(market, df, correlation_data)
        vol_sig = self._vol.generate_signal(market, df, correlation_data)
        adaptive_sig = self._adaptive.generate_signal(market, df, correlation_data)

        pa_label = _signal_label(pa_sig)
        vol_label = _signal_label(vol_sig)
        adaptive_label = _signal_label(adaptive_sig)

        selected: TradingSignal | None = None
        engine = ENGINE_NONE
        reason = "no_valid_signal"

        if _is_valid(pa_sig):
            selected = _normalize_pa_signal(pa_sig)
            engine = ENGINE_PA
            reason = "priority_pa"
        elif not self._pa_only:
            if _is_valid(vol_sig):
                selected = vol_sig
                engine = ENGINE_VOL
                reason = "pa_no_signal_vol_selected"
            elif _is_valid(adaptive_sig):
                selected = adaptive_sig
                engine = ENGINE_ADAPTIVE
                reason = "pa_vol_no_signal_adaptive_fallback"
        elif _is_valid(vol_sig) or _is_valid(adaptive_sig):
            reason = "pa_only_vol_adaptive_logged_not_selected"

        record_router_decision(
            timestamp=ts,
            symbol=market.symbol,
            timeframe=market.timeframe,
            pa_signal=pa_label,
            vol_signal=vol_label,
            adaptive_signal=adaptive_label,
            selected_engine=engine,
            rejection_reason=reason if selected is None else reason,
            extra={
                "selected_direction": _signal_label(selected),
                "pa_strategy": pa_sig.strategy_name if pa_sig else "",
                "vol_strategy": vol_sig.strategy_name if vol_sig else "",
                "adaptive_strategy": adaptive_sig.strategy_name if adaptive_sig else "",
                "pa_production_lock": self._pa_only,
            },
        )
        try:
            from tradingbot.services.live_loop_health import record_router_activity

            record_router_activity(
                pa_hold=pa_label == "HOLD",
                pa_signal=pa_label in ("BUY", "SELL"),
                selected_engine_none=engine == ENGINE_NONE,
            )
        except Exception:
            pass

        if selected is None:
            logger.debug(
                "Router HOLD | pa=%s vol=%s adaptive=%s reason=%s",
                pa_label,
                vol_label,
                adaptive_label,
                reason,
            )
            return None

        logger.info(
            "Router selected %s | %s | pa=%s vol=%s adaptive=%s reason=%s",
            engine,
            selected.direction.name,
            pa_label,
            vol_label,
            adaptive_label,
            reason,
        )
        return _tag_router(selected, engine=engine, pa=pa_label, vol=vol_label, adaptive=adaptive_label)
