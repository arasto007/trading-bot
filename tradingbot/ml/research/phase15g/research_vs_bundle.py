"""Phase 15G — research vs frozen bundle side-by-side comparison."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_7.config import load_phase14_6_policy
from tradingbot.ml.research.phase14_6.research_calibrator import ResearchCalibratedAdapter, ResearchCalibrationPolicy
from tradingbot.ml.research.phase15g.bundle_statistics import distribution_stats


def compare_research_vs_frozen(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    days: int = 180,
    stride: int = 5,
    max_rows: int = 500,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    frozen_registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    frozen_range = getattr(frozen_registry.get("phase9_9"), "inner", None)
    frozen_trend = getattr(frozen_registry.get("trend_rf_v40"), "inner", None)

    research_range, research_trend = load_production_engines(window, symbol=symbol, seed=seed)

    policy = load_phase14_6_policy(base_dir)
    cal_threshold = float(policy.get("confidence_threshold", 0.30))

    frozen_method, _ = load_recovered_calibration(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=frozen_range, trend_engine=frozen_trend,
    )
    research_method, _ = load_recovered_calibration(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=research_range, trend_engine=research_trend,
    )

    frozen_adapter = ResearchCalibratedAdapter(
        DecisionOrchestrator(),
        calibration_method=frozen_method,
        policy=ResearchCalibrationPolicy(min_calibrated_confidence=cal_threshold),
    )
    research_adapter = ResearchCalibratedAdapter(
        DecisionOrchestrator(),
        calibration_method=research_method,
        policy=ResearchCalibrationPolicy(min_calibrated_confidence=cal_threshold),
    )

    rows: list[dict[str, Any]] = []
    prob_diffs: list[float] = []
    conf_diffs: list[float] = []
    direction_mismatches = 0

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

        f_cal = frozen_adapter.decide(ctx_f)
        r_cal = research_adapter.decide(ctx_r)

        f_prob = float(f_cal.decision.metadata.get("probability", 0))
        r_prob = float(r_cal.decision.metadata.get("probability", 0))
        prob_diffs.append(abs(f_prob - r_prob))
        conf_diffs.append(abs(float(f_cal.final_confidence) - float(r_cal.final_confidence)))

        if f_cal.final_action != r_cal.final_action:
            direction_mismatches += 1

        if len(rows) < max_rows:
            source = "engine_probability"
            if f_prob != r_prob:
                source = "trend_engine_model_mismatch"
            elif f_cal.raw_confidence.raw_value != r_cal.raw_confidence.raw_value:
                source = "decision_compression"
            elif f_cal.final_confidence != r_cal.final_confidence:
                source = "platt_fit_difference"

            rows.append({
                "timestamp": str(row.get("timestamp", "")),
                "regime": ctx_f.regime,
                "frozen": {
                    "probability": round(f_prob, 6),
                    "raw_confidence": round(float(f_cal.raw_confidence.raw_value), 6),
                    "calibrated_confidence": round(float(f_cal.final_confidence), 6),
                    "direction": f_cal.final_action,
                    "engine_signal": str(f_cal.raw_confidence.engine_signal),
                },
                "research": {
                    "probability": round(r_prob, 6),
                    "raw_confidence": round(float(r_cal.raw_confidence.raw_value), 6),
                    "calibrated_confidence": round(float(r_cal.final_confidence), 6),
                    "direction": r_cal.final_action,
                    "engine_signal": str(r_cal.raw_confidence.engine_signal),
                },
                "difference_source": source,
            })

    frozen_accepted = sum(1 for r in rows if r["frozen"]["direction"] in ("BUY", "SELL"))
    research_accepted = sum(1 for r in rows if r["research"]["direction"] in ("BUY", "SELL"))

    return {
        "phase": "15G",
        "bars_compared": len(rows),
        "direction_mismatches": direction_mismatches,
        "probability_diff": distribution_stats(prob_diffs),
        "confidence_diff": distribution_stats(conf_diffs),
        "frozen_accepted_at_cal_threshold": frozen_accepted,
        "research_accepted_at_cal_threshold": research_accepted,
        "primary_difference_source": (
            "trend_engine_model_mismatch"
            if distribution_stats(prob_diffs)["mean"] > 0.05
            else "platt_fit_on_different_engine_outputs"
        ),
        "sample_rows": rows[:50],
    }
