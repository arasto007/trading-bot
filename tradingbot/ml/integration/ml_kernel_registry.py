"""Phase 15B — ML kernel strategy registry with automatic legacy fallback."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.kernel_adapter import KernelAdapter
from tradingbot.ml.integration.monitoring import log_fallback_event
from tradingbot.ml.integration.config import is_legacy_fallback_allowed, is_ml_kernel_enabled
from tradingbot.ports.strategies import IStrategyRegistry

logger = logging.getLogger(__name__)


class MLKernelRegistry:
    """
    IStrategyRegistry implementation routing to KernelAdapter with legacy fallback.

    When USE_ML_KERNEL=false, delegates entirely to LegacyStrategyRegistry.
    """

    def __init__(
        self,
        legacy_config: dict[str, Any] | None = None,
        *,
        legacy: LegacyStrategyRegistry | None = None,
        adapter: KernelAdapter | None = None,
        base_dir: str | None = None,
    ) -> None:
        self._config = legacy_config or {}
        self._legacy = legacy or LegacyStrategyRegistry(legacy_config)
        self._adapter = adapter
        self._base_dir = base_dir or self._config.get("BASE_DIR")
        self.fallback_count = 0
        self.ml_count = 0
        self.hold_count = 0

    def _safe_hold(self, market: MarketKey, reason: str, *, checks: dict | None = None) -> None:
        logger.warning("ML kernel safe HOLD (fallback disabled): %s", reason)
        log_fallback_event(reason, detail=checks, base_dir=self._base_dir)
        self.hold_count += 1
        self._last_source = "safe_hold"
        return None

    def _maybe_legacy_fallback(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None,
        reason: str,
        *,
        checks: dict | None = None,
    ) -> TradingSignal | None:
        if not is_legacy_fallback_allowed():
            return self._safe_hold(market, reason, checks=checks)
        logger.warning("ML kernel legacy fallback: %s", reason)
        self.fallback_count += 1
        self._last_source = "legacy_fallback"
        return self._legacy.generate_signal(market, df, correlation_data)

    @property
    def last_source(self) -> str:
        return getattr(self, "_last_source", "unknown")

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        if not is_ml_kernel_enabled():
            self._last_source = "legacy"
            return self._legacy.generate_signal(market, df, correlation_data)

        if self._adapter is None:
            return self._maybe_legacy_fallback(
                market, df, correlation_data, "adapter_not_injected",
            )

        try:
            signal = self._adapter.generate_signal(
                market, df, correlation_data, config=self._config,
            )
            self.ml_count += 1
            self._last_source = "ml_kernel"
            if signal is not None:
                meta = dict(signal.metadata or {})
                meta["signal_source"] = "ml_kernel"
                signal.metadata = meta
            return signal
        except KernelFallbackError as exc:
            logger.warning("ML kernel error: %s", exc.reason)
            try:
                from tradingbot.ml.monitoring.fallback_monitor import FallbackMonitor
                FallbackMonitor(self._base_dir).record(exc.reason, detail=exc.checks)
            except Exception:
                log_fallback_event(exc.reason, detail=exc.checks, base_dir=self._base_dir)
            return self._maybe_legacy_fallback(
                market, df, correlation_data, exc.reason, checks=exc.checks,
            )
        except Exception as exc:
            logger.exception("ML kernel unexpected error")
            return self._maybe_legacy_fallback(
                market,
                df,
                correlation_data,
                "unexpected_exception",
                checks={"error": str(exc)},
            )

    def stats(self) -> dict[str, Any]:
        return {
            "ml_count": self.ml_count,
            "fallback_count": self.fallback_count,
            "hold_count": self.hold_count,
            "last_source": self.last_source,
            "ml_enabled": is_ml_kernel_enabled(),
            "legacy_fallback_allowed": is_legacy_fallback_allowed(),
        }
