"""Phase 10.1 — build TradingKernel with ML shadow dependencies (no kernel edits)."""

from __future__ import annotations

import os
from typing import Any

from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
from tradingbot.adapters.risk_gate import create_risk_gate
from tradingbot.adapters.stubs import StubExecutor
from tradingbot.config.settings import KernelSettings
from tradingbot.kernel.trading_kernel import TradingKernel
from tradingbot.ml.integration.composite_registry import CompositeStrategyRegistry
from tradingbot.ml.integration.config import is_ml_shadow_enabled, is_ml_shadow_mode
from tradingbot.ml.integration.replay_market_data import ReplayMarketDataAdapter
from tradingbot.ml.integration.shadow_execution_guard import ShadowExecutionGuard


def build_kernel_shadow(
    market_data: Any,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    legacy_config: dict[str, Any] | None = None,
    base_dir: str | None = None,
    seed: int = 42,
) -> tuple[TradingKernel, CompositeStrategyRegistry, ShadowExecutionGuard]:
    """Construct kernel with ML composite registry and shadow execution guard."""
    os.environ.setdefault("ENABLE_ML_SHADOW", "true")
    os.environ.setdefault("ML_SHADOW_MODE", "true")

    cfg = dict(legacy_config or _default_legacy_config())
    settings = KernelSettings(
        symbols=[symbol.upper()],
        timeframes=[timeframe.upper()],
        cycle_interval_seconds=1.0,
        extra=cfg,
    )

    strategies = CompositeStrategyRegistry(cfg, base_dir=base_dir, seed=seed)
    risk_gate = create_risk_gate(cfg)
    guard = ShadowExecutionGuard(inner=StubExecutor())

    kernel = TradingKernel(
        settings=settings,
        market_data=market_data,
        indicators=TechnicalIndicatorEngine(cfg),
        strategies=strategies,
        risk=risk_gate,
        executor=guard,
        position_manager=None,
    )
    return kernel, strategies, guard


def _default_legacy_config() -> dict[str, Any]:
    try:
        from tradingbot.adapters.legacy_loader import load_legacy_config

        return load_legacy_config()
    except Exception:
        return {"INITIAL_BALANCE": 10_000, "RISK_PER_TRADE": 0.005}
