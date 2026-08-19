"""Phase 22I — inject research orchestrator into ML stack for backtest simulation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.decision_engine.decision_policy import DecisionPolicy
from tradingbot.ml.integration.factory import MLKernelStack
from tradingbot.ml.research.phase22i.candidates import PolicyCandidate


def rebuild_stack_with_orchestrator(
    base_stack: MLKernelStack,
    orchestrator: Any,
    *,
    base_dir: str | None,
    symbol: str = "XAUUSD",
) -> MLKernelStack:
    from tradingbot.ml.confidence_mapping.production_adapter import build_mapped_production_risk
    from tradingbot.ml.integration.recovered_calibration import build_production_calibrated_adapter
    from tradingbot.ml.research.phase14_7.config import DEFAULT_MAX_RISK_PERCENT, DEFAULT_QUALITY_THRESHOLD
    from tradingbot.ml.research.phase22c.config import load_phase22c_config
    from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
    from tradingbot.ml.risk_intelligence.risk_policy import RiskPolicy
    from tradingbot.ml.risk_intelligence.risk_types import AccountState, HistoricalMetrics
    from tradingbot.ml.trade_quality.adapter import TradeQualityAdapter
    from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
    from tradingbot.ml.trade_quality.quality_policy import QualityPolicy

    cfg22 = load_phase22c_config()
    calibration = build_production_calibrated_adapter(
        orchestrator,
        base_dir=base_dir,
        symbol=symbol,
    )
    history = HistoricalMetrics(engine_trade_count={"phase9_9": 3788, "trend_rf_v41": 1205})
    risk_engine = AdaptiveRiskEngine(policy=RiskPolicy(max_risk_percent=DEFAULT_MAX_RISK_PERCENT))
    risk = build_mapped_production_risk(
        calibration,
        base_dir=base_dir,
        symbol=symbol,
        risk_engine=risk_engine,
        account=AccountState(),
        history=history,
    )
    quality_threshold = cfg22.quality_threshold if cfg22.enabled else DEFAULT_QUALITY_THRESHOLD
    quality = TradeQualityAdapter(
        risk,
        quality_engine=TradeQualityEngine(
            policy=QualityPolicy(threshold=quality_threshold),
            history=history,
        ),
    )
    return MLKernelStack(
        registry=base_stack.registry,
        orchestrator=orchestrator,
        calibration=calibration,
        risk=risk,
        quality=quality,
    )


def simulate_candidate_backtest(candidate: PolicyCandidate, *, base_dir: str | None) -> Any:
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.research.phase22c.config import load_phase22c_config
    from tradingbot.ml.decision_engine.decision_policy import DecisionPolicy

    PipelineCache.reset()
    cfg22 = load_phase22c_config()
    policy = DecisionPolicy(
        min_confidence=cfg22.decision_min_confidence if cfg22.enabled else DecisionPolicy().min_confidence,
    )
    base = build_ml_kernel_stack(base_dir=base_dir)
    orch = candidate.build_orchestrator(base_dir=base_dir, policy=policy)
    return rebuild_stack_with_orchestrator(base, orch, base_dir=base_dir)
