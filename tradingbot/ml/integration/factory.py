"""Phase 15B — dependency-injected ML pipeline factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.ml.data.paths import normalize_ml_base_dir
from tradingbot.ml.confidence_mapping.production_adapter import build_mapped_production_risk
from tradingbot.ml.integration.recovered_calibration import build_production_calibrated_adapter
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.integration.config import is_ml_kernel_enabled, is_ml_kernel_env_set
from tradingbot.ml.integration.startup_diagnostics import log_engine_selection
from tradingbot.ml.integration.ml_kernel_registry import MLKernelRegistry
from tradingbot.ml.integration.kernel_adapter import KernelAdapter, MLKernelDependencies
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.ml.monitoring.observer import MonitoredKernelAdapter, MonitoringHub
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.decision_engine.decision_policy import DecisionPolicy
from tradingbot.ml.research.phase14_7.config import DEFAULT_MAX_RISK_PERCENT, DEFAULT_QUALITY_THRESHOLD
from tradingbot.ml.research.phase22c.config import load_phase22c_config
from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
from tradingbot.ml.risk_intelligence.risk_policy import RiskPolicy
from tradingbot.ml.risk_intelligence.risk_types import AccountState, HistoricalMetrics
from tradingbot.ml.trade_quality.adapter import TradeQualityAdapter
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
from tradingbot.ml.trade_quality.quality_policy import QualityPolicy
from tradingbot.ports.strategies import IStrategyRegistry


class UnconfiguredEngineRegistry:
    """Returns no signal when USE_ML_KERNEL was not explicitly set."""

    def __init__(self, selection_reason: str = "") -> None:
        self._reason = selection_reason
        self.last_source = "unconfigured"

    def generate_signal(self, market, df, correlation_data=None):
        return None

    def stats(self) -> dict[str, Any]:
        return {"last_source": self.last_source, "reason": self._reason}


@dataclass
class MLKernelStack:
    registry: EngineRegistry
    orchestrator: DecisionOrchestrator
    calibration: Any
    risk: Any
    quality: TradeQualityAdapter

    def as_dependencies(self, *, base_dir: str | None = None, symbol: str = PRIMARY_SYMBOL) -> MLKernelDependencies:
        return MLKernelDependencies(
            registry=self.registry,
            orchestrator=self.orchestrator,
            calibration=self.calibration,
            risk=self.risk,
            quality=self.quality,
            base_dir=base_dir,
            symbol=symbol,
        )


def build_ml_kernel_stack(
    *,
    base_dir: str | None = None,
    symbol: str = PRIMARY_SYMBOL,
    use_range_recovery: bool = True,
) -> MLKernelStack:
    """Build injected ML stack — TradingKernel must never call this directly."""
    base_dir = normalize_ml_base_dir(base_dir)
    cfg22 = load_phase22c_config()
    PipelineCache.configure(base_dir=base_dir, symbol=symbol)
    PipelineCache.warm_datasets(symbol=symbol, base_dir=base_dir)
    registry = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
    if cfg22.enabled:
        from tradingbot.ml.research.phase22c.thresholds import apply_phase22c_range_thresholds

        apply_phase22c_range_thresholds(registry, cfg22)
    policy = DecisionPolicy(
        min_confidence=cfg22.decision_min_confidence if cfg22.enabled else DecisionPolicy().min_confidence,
    )
    if use_range_recovery:
        from tradingbot.ml.research.phase15i.recovery_adapter import build_range_recovery_orchestrator

        orchestrator = build_range_recovery_orchestrator(base_dir=base_dir)
        if cfg22.enabled:
            orchestrator.inner.policy = policy
    else:
        orchestrator = DecisionOrchestrator(base_dir=base_dir, policy=policy)
    calibration = build_production_calibrated_adapter(
        orchestrator,
        base_dir=base_dir,
        symbol=symbol,
    )
    history = HistoricalMetrics(engine_trade_count={"phase9_9": 3788, "trend_rf_v40": 1205})
    risk_engine = AdaptiveRiskEngine(policy=RiskPolicy(max_risk_percent=DEFAULT_MAX_RISK_PERCENT))
    risk = build_mapped_production_risk(
        calibration,
        base_dir=base_dir,
        symbol=symbol,
        risk_engine=risk_engine,
        account=AccountState(),
        history=history,
    )
    quality_threshold = (
        cfg22.quality_threshold if cfg22.enabled else DEFAULT_QUALITY_THRESHOLD
    )
    quality = TradeQualityAdapter(
        risk,
        quality_engine=TradeQualityEngine(
            policy=QualityPolicy(threshold=quality_threshold),
            history=history,
        ),
    )
    return MLKernelStack(
        registry=registry,
        orchestrator=orchestrator,
        calibration=calibration,
        risk=risk,
        quality=quality,
    )


def build_kernel_adapter(
    *,
    base_dir: str | None = None,
    symbol: str = PRIMARY_SYMBOL,
    stack: MLKernelStack | None = None,
    enable_monitoring: bool = False,
) -> KernelAdapter:
    base_dir = normalize_ml_base_dir(base_dir)
    ml_stack = stack or build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    inner = KernelAdapter(ml_stack.as_dependencies(base_dir=base_dir, symbol=symbol))
    if not enable_monitoring:
        return inner
    hub = MonitoringHub(base_dir)
    return MonitoredKernelAdapter(inner, hub)  # type: ignore[return-value]


def _maybe_wrap_shadow(
    registry: IStrategyRegistry,
    legacy_config: dict[str, Any] | None,
    *,
    base_dir: str | None,
    ml_enabled: bool,
) -> IStrategyRegistry:
    from tradingbot.ml.integration.config import is_ml_shadow_enabled

    if is_ml_shadow_enabled() and not ml_enabled:
        from tradingbot.adapters.shadow_strategy_registry import ShadowStrategyRegistry

        return ShadowStrategyRegistry(registry, legacy_config, base_dir=base_dir)
    return registry


def build_strategy_registry(
    legacy_config: dict[str, Any] | None = None,
    *,
    base_dir: str | None = None,
    symbol: str = PRIMARY_SYMBOL,
    stack: MLKernelStack | None = None,
) -> IStrategyRegistry:
    """Select the live strategy registry.

    Branch order (matches runtime, not historical VOL-default docs):
    1. Gate-downgrade ML if USE_ML_KERNEL=true but the live gate is closed.
    2. MultiEngineRouterRegistry when MULTI_ENGINE_ROUTER_ENABLED (default live).
    3. AdaptiveRegimeStrategyRegistry when ADAPTIVE_REGIME_ENABLED.
    4. VolRegimeStrategyRegistry when VOL_REGIME_ENABLED.
    5. MLKernelRegistry only when ML remains enabled after the gate.
    6. UnconfiguredEngineRegistry when USE_ML_KERNEL is unset and router/adaptive/vol are off.
    7. LegacyStrategyRegistry otherwise (optional ML-shadow wrap).
    """
    from tradingbot.config.live import get_live_config

    selection = log_engine_selection()
    if base_dir is None and legacy_config:
        base_dir = legacy_config.get("BASE_DIR")
    base_dir = normalize_ml_base_dir(base_dir)
    legacy = LegacyStrategyRegistry(legacy_config)
    live_cfg = get_live_config()
    adaptive_on = bool(live_cfg.get("ADAPTIVE_REGIME_ENABLED", False))
    vol_regime_on = bool(live_cfg.get("VOL_REGIME_ENABLED", False))
    router_on = bool(live_cfg.get("MULTI_ENGINE_ROUTER_ENABLED", False))
    ml_enabled = is_ml_kernel_enabled()
    if ml_enabled:
        from tradingbot.ml.shadow.shadow_gate import evaluate_ml_live_gate

        gate = evaluate_ml_live_gate()
        if not gate.get("allowed"):
            import logging

            logging.getLogger(__name__).warning(
                "USE_ML_KERNEL=true blocked by shadow gate — staying on inner engine "
                "(closed=%s pf_agrees=%s need n>=%s pf>%s)",
                gate.get("closed_trades"),
                gate.get("pf_ml_agrees"),
                gate.get("min_trades"),
                gate.get("pf_gate"),
            )
            ml_enabled = False

    if router_on and not ml_enabled:
        from tradingbot.adapters.multi_engine_router import MultiEngineRouterRegistry

        return _maybe_wrap_shadow(
            MultiEngineRouterRegistry(legacy_config),
            legacy_config,
            base_dir=base_dir,
            ml_enabled=ml_enabled,
        )

    if adaptive_on and not ml_enabled:
        from tradingbot.adapters.adaptive_regime_strategy_registry import (
            AdaptiveRegimeStrategyRegistry,
        )

        return _maybe_wrap_shadow(
            AdaptiveRegimeStrategyRegistry(legacy_config),
            legacy_config,
            base_dir=base_dir,
            ml_enabled=ml_enabled,
        )

    if vol_regime_on and not ml_enabled:
        from tradingbot.adapters.vol_regime_strategy_registry import VolRegimeStrategyRegistry

        return _maybe_wrap_shadow(
            VolRegimeStrategyRegistry(legacy_config),
            legacy_config,
            base_dir=base_dir,
            ml_enabled=ml_enabled,
        )

    if ml_enabled:
        adapter = build_kernel_adapter(
            base_dir=base_dir, symbol=symbol, stack=stack, enable_monitoring=True,
        )
        return MLKernelRegistry(legacy_config, legacy=legacy, adapter=adapter)

    if not is_ml_kernel_env_set() and not vol_regime_on:
        return UnconfiguredEngineRegistry(selection.reason)

    return _maybe_wrap_shadow(legacy, legacy_config, base_dir=base_dir, ml_enabled=ml_enabled)


def resolve_live_equity_for_tier() -> float | None:
    """Best-effort MT5 equity for capital-adaptive live SL/TP."""
    from tradingbot.services.runtime_truth import get_live_equity, refresh_live_equity_from_mt5

    equity = get_live_equity()
    if equity is not None and equity > 0:
        return equity
    if refresh_live_equity_from_mt5(log_freeze=False):
        return get_live_equity()
    return None


def resolve_live_account_tier(*, fallback: str | None = None) -> str | None:
    """Resolve capital-adaptive tier from live MT5 equity — no assumed tier when unknown."""
    from tradingbot.adapters.risk_gate import detect_account_tier

    equity = resolve_live_equity_for_tier()
    if equity is None or equity <= 0:
        return None
    return detect_account_tier(equity).value
