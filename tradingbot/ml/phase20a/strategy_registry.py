"""Phase 20A — strategy registry with observed ML kernel."""

from __future__ import annotations

from typing import Any

from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.ml_kernel_registry import MLKernelRegistry
from tradingbot.ml.phase20a.kernel_observer import Phase20aObservedAdapter
from tradingbot.ml.phase20a.reporter import Phase20aReporter
from tradingbot.ml.phase20a.safety_monitor import Phase20aSafetyMonitor


def build_phase20a_strategy_registry(
    legacy_config: dict[str, Any] | None,
    *,
    base_dir: str | None,
    symbol: str,
    reporter: Phase20aReporter,
    safety: Phase20aSafetyMonitor,
    stack=None,
) -> MLKernelRegistry:
    ml_stack = stack or build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
    inner = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=ml_stack)
    observed = Phase20aObservedAdapter(inner, reporter=reporter, safety=safety)
    legacy = LegacyStrategyRegistry(legacy_config)
    registry = MLKernelRegistry(legacy_config, legacy=legacy, adapter=observed, base_dir=base_dir)  # type: ignore[arg-type]
    return registry
