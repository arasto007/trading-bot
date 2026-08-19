"""Phase 10.1 — Composite strategy registry (legacy + ML shadow)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.integration.config import is_ml_shadow_enabled
from tradingbot.ml.integration.ml_strategy import MLShadowStrategy, STRATEGY_NAME
from tradingbot.ports.strategies import IStrategyRegistry

logger = logging.getLogger(__name__)


class CompositeStrategyRegistry:
    """
    When ENABLE_ML_SHADOW=true: prefer ML signal, fallback to rule strategies.
    Implements IStrategyRegistry without modifying kernel or legacy registry.
    """

    def __init__(
        self,
        legacy_config: dict[str, Any] | None = None,
        *,
        base_dir: str | None = None,
        seed: int = 42,
        legacy: LegacyStrategyRegistry | None = None,
        ml: MLShadowStrategy | None = None,
    ) -> None:
        self._legacy = legacy or LegacyStrategyRegistry(legacy_config)
        self._ml = ml or MLShadowStrategy(base_dir=base_dir, seed=seed)
        self._last_ml_meta: dict[str, Any] = {}

    @property
    def last_ml_meta(self) -> dict[str, Any]:
        return dict(self._last_ml_meta)

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        ml_signal: TradingSignal | None = None
        rule_signal: TradingSignal | None = None

        if is_ml_shadow_enabled():
            try:
                ml_signal = self._ml.generate_signal(market, df, correlation_data)
            except Exception as exc:
                logger.warning("MLShadowStrategy failed: %s", exc)

        try:
            rule_signal = self._legacy.generate_signal(market, df, correlation_data)
        except Exception as exc:
            logger.warning("LegacyStrategyRegistry failed: %s", exc)

        self._last_ml_meta = {
            "ml_probability": (ml_signal.metadata or {}).get("ml_probability") if ml_signal else None,
            "ml_direction": ml_signal.direction.name if ml_signal else "HOLD",
            "rule_direction": rule_signal.direction.name if rule_signal else "HOLD",
        }

        if ml_signal is not None and ml_signal.direction != SignalDirection.HOLD:
            meta = dict(ml_signal.metadata or {})
            meta["rule_signal"] = rule_signal.direction.name if rule_signal else "HOLD"
            meta["signal_source"] = "ml_shadow"
            ml_signal.metadata = meta
            ml_signal.strategy_name = STRATEGY_NAME
            return ml_signal

        if rule_signal is not None and rule_signal.direction != SignalDirection.HOLD:
            meta = dict(rule_signal.metadata or {})
            meta["signal_source"] = "rule_strategy"
            rule_signal.metadata = meta
            return rule_signal

        return None
