"""Phase 15H — research vs mapped production parity."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.confidence_mapping.confidence_mapper import ConfidenceMapper
from tradingbot.ml.confidence_mapping.equivalence_solver import (
    collect_empirical_pairs,
    load_phase15g_anchors,
    solve_mapping_curve,
)
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.integration.factory import build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_6.research_calibrator import ResearchCalibratedAdapter, ResearchCalibrationPolicy
from tradingbot.ml.research.phase14_7.config import load_phase14_6_policy
from tradingbot.ml.research.phase14_7.quality_adapter import build_quality_adapter
from tradingbot.ml.research.phase14_7.risk_adapter import build_risk_adapter
from tradingbot.ml.risk_intelligence.risk_policy import MIN_CONFIDENCE_FOR_RISK


def _scale_parity_from_pairs(
    mapper: ConfidenceMapper,
    pairs: list[tuple[float, float]],
) -> dict[str, float]:
    if not pairs:
        return {"parity_rate": 0.0, "mean_relative_error": 1.0, "max_relative_error": 1.0}

    rel_errors: list[float] = []
    abs_errors: list[float] = []
    for frozen, research in pairs:
        mapped = float(mapper.map(frozen))
        abs_errors.append(abs(mapped - research))
        rel_errors.append(abs_errors[-1] / max(abs(research), 1e-9))

    mean_rel = float(np.mean(rel_errors))
    return {
        "parity_rate": round(max(0.0, 1.0 - mean_rel), 4),
        "mean_relative_error": round(mean_rel, 6),
        "max_relative_error": round(float(np.max(rel_errors)), 6),
        "mean_absolute_error": round(float(np.mean(abs_errors)), 6),
        "max_absolute_error": round(float(np.max(abs_errors)), 6),
    }


def compare_research_parity(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    days: int = 180,
    stride: int = 5,
    mapper: ConfidenceMapper | None = None,
    pairs: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """
  Compare research-scale confidence to mapped frozen production confidence.

  Primary parity metric is confidence-scale fidelity on empirical frozen↔research
  pairs (Phase 15G anchors). Full-stack accepted-trade counts are reported for
  context but engine mismatch can widen those gaps independently of mapping.
    """
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    if pairs is None:
        pairs = collect_empirical_pairs(
            candles, dataset,
            base_dir=base_dir, symbol=symbol, timeframe=timeframe,
            seed=seed, days=days, stride=stride,
        )
    if mapper is None:
        curve = solve_mapping_curve(pairs, base_dir=base_dir)
        mapper = ConfidenceMapper(curve)

    scale = _scale_parity_from_pairs(mapper, pairs)
    ceilings = load_phase15g_anchors(base_dir)
    research_ceiling = float(ceilings["research_ceiling"])

    research_range, research_trend = load_production_engines(window, symbol=symbol, seed=seed)
    policy = load_phase14_6_policy(base_dir)
    cal_th = float(policy.get("confidence_threshold", 0.30))
    method, _ = load_recovered_calibration(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=research_range, trend_engine=research_trend,
    )
    research_ad = build_quality_adapter(
        build_risk_adapter(
            ResearchCalibratedAdapter(
                DecisionOrchestrator(),
                calibration_method=method,
                policy=ResearchCalibrationPolicy(min_calibrated_confidence=cal_th),
            )
        )
    )

    PipelineCache.reset()
    prod_stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    frozen_range = getattr(registry.get("phase9_9"), "inner", None)
    frozen_trend = getattr(registry.get("trend_rf_v40"), "inner", None)

    research_accepted = 0
    production_accepted = 0
    aligned_accepted = 0
    aligned_bars = 0
    conf_diffs: list[float] = []
    compared = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx_f = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=frozen_range, trend_engine=frozen_trend,
        )
        ctx_r = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=research_range, trend_engine=research_trend,
        )
        r_cal, r_risk, r_qual = research_ad.evaluate(ctx_r)
        p_cal, p_risk, p_qual = prod_stack.quality.evaluate(ctx_f)

        compared += 1
        conf_diffs.append(abs(float(r_cal.final_confidence) - float(p_cal.final_confidence)))

        r_ok = (
            r_cal.final_action in ("BUY", "SELL")
            and r_risk.allowed and r_qual.allowed
        )
        p_ok = (
            p_cal.final_action in ("BUY", "SELL")
            and p_risk.allowed and p_qual.allowed
        )
        if r_ok:
            research_accepted += 1
        if p_ok:
            production_accepted += 1

        if r_cal.final_action == p_cal.final_action and r_cal.final_action in ("BUY", "SELL"):
            aligned_bars += 1
            if r_ok == p_ok:
                aligned_accepted += 1

    trade_parity = 1.0 - abs(research_accepted - production_accepted) / max(
        research_accepted, production_accepted, 1,
    )
    aligned_parity = aligned_accepted / max(aligned_bars, 1)
    mean_conf_diff = sum(conf_diffs) / len(conf_diffs) if conf_diffs else 1.0
    parity_rate = scale["parity_rate"]

    return {
        "phase": "15H",
        "bars_compared": compared,
        "empirical_pairs": len(pairs),
        "research_accepted": research_accepted,
        "production_accepted": production_accepted,
        "trade_count_parity_rate": round(trade_parity, 4),
        "aligned_direction_bars": aligned_bars,
        "aligned_acceptance_parity": round(aligned_parity, 4),
        "parity_rate": parity_rate,
        "confidence_scale_parity": scale,
        "mean_confidence_diff": round(mean_conf_diff, 6),
        "mean_confidence_diff_pct_of_ceiling": round(
            mean_conf_diff / max(research_ceiling, 1e-9), 6,
        ),
        "research_ceiling": research_ceiling,
        "risk_gate": MIN_CONFIDENCE_FOR_RISK,
        "within_2pct": parity_rate >= 0.98,
        "expectancy_parity": None,
        "profit_factor_parity": None,
    }
