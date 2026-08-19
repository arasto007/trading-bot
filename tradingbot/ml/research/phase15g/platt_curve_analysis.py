"""Phase 15G — Platt calibration curve analysis."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.confidence_engine.calibration_types import RawConfidence
from tradingbot.ml.confidence_engine.validator import raw_confidence_from_decision
from tradingbot.ml.decision_engine.decision_types import MarketContext
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase15g.bundle_statistics import distribution_stats
from tradingbot.ml.research.phase15g.config import PLATT_CURVE_POINTS


def _load_frozen_platt(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None,
    symbol: str,
    timeframe: str,
    seed: int,
) -> Any:
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_inner = getattr(registry.get("phase9_9"), "inner", None)
    trend_inner = getattr(registry.get("trend_rf_v40"), "inner", None)
    method, _ = load_recovered_calibration(
        candles, dataset,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=range_inner, trend_engine=trend_inner,
    )
    return method


def _synthetic_raw(value: float, *, engine: str = "trend_rf_v40") -> RawConfidence:
    return RawConfidence(
        raw_value=value,
        engine=engine,
        regime="TREND",
        model_probability=value,
        regime_strength=0.8,
        market_quality=0.7,
        session="london",
        volatility=50.0,
        volatility_state="normal",
        engine_signal="SELL",
    )


def analyze_platt_curve(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    days: int = 180,
    stride: int = 5,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    method = _load_frozen_platt(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
    )

    grid = np.linspace(0.01, 1.0, PLATT_CURVE_POINTS)
    synthetic_curve: list[dict[str, float]] = []
    max_synthetic = 0.0
    for raw in grid:
        calibrated = float(method.calibrate(_synthetic_raw(float(raw))).calibrated_value)
        max_synthetic = max(max_synthetic, calibrated)
        synthetic_curve.append({"raw_input": round(float(raw), 4), "calibrated": round(calibrated, 6)})

    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_inner = getattr(registry.get("phase9_9"), "inner", None)
    trend_inner = getattr(registry.get("trend_rf_v40"), "inner", None)
    unified = build_unified_frame(window, dataset)
    orchestrator = DecisionOrchestrator()

    empirical: list[dict[str, float]] = []
    raw_vals: list[float] = []
    cal_vals: list[float] = []

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_inner, trend_engine=trend_inner,
        )
        decision = orchestrator.decide(ctx)
        raw = raw_confidence_from_decision(decision, ctx)
        calibrated = method.calibrate(raw)
        rv = float(raw.raw_value)
        cv = float(calibrated.calibrated_value)
        raw_vals.append(rv)
        cal_vals.append(cv)
        if len(empirical) < 200 and str(raw.engine_signal) in ("BUY", "SELL"):
            empirical.append({
                "raw_confidence": round(rv, 6),
                "model_probability": round(float(raw.model_probability), 6),
                "calibrated": round(cv, 6),
                "engine_signal": str(raw.engine_signal),
            })

    max_empirical = max(cal_vals) if cal_vals else 0.0
    max_attainable = max(max_synthetic, max_empirical)

    return {
        "phase": "15G",
        "calibration_method": "platt",
        "fit_engines": "frozen EngineRegistry",
        "synthetic_curve": synthetic_curve,
        "empirical_sample": empirical[:50],
        "empirical_raw_distribution": distribution_stats(raw_vals),
        "empirical_calibrated_distribution": distribution_stats(cal_vals),
        "maximum_attainable_confidence": {
            "synthetic_grid_max": round(max_synthetic, 6),
            "empirical_max": round(max_empirical, 6),
            "combined_max": round(max_attainable, 6),
        },
        "mapping_examples": synthetic_curve[:: max(1, len(synthetic_curve) // 8)],
    }
