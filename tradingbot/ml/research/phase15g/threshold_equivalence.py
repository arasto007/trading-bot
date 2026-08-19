"""Phase 15G — threshold equivalence between research and frozen bundle."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.confidence_engine.calibration_types import RawConfidence
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase15g.config import RESEARCH_CALIB_THRESHOLD


def _find_frozen_equivalent(
    research_method: Any,
    frozen_method: Any,
    *,
    target: float,
    lo: float = 0.01,
    hi: float = 1.0,
    steps: int = 200,
) -> dict[str, Any]:
    """Find frozen calibrated value when research calibrated equals target."""

    def _research_cal(raw: float) -> float:
        r = RawConfidence(
            raw_value=raw, engine="trend_rf_v40", regime="TREND",
            model_probability=raw, regime_strength=0.8, market_quality=0.7,
            session="london", volatility=50.0, volatility_state="normal",
            engine_signal="SELL",
        )
        return float(research_method.calibrate(r).calibrated_value)

    raw_grid = np.linspace(lo, hi, steps)
    best_raw = lo
    best_diff = 1e9
    for raw in raw_grid:
        diff = abs(_research_cal(float(raw)) - target)
        if diff < best_diff:
            best_diff = diff
            best_raw = float(raw)

    frozen_at_best = float(
        frozen_method.calibrate(
            RawConfidence(
                raw_value=best_raw, engine="trend_rf_v40", regime="TREND",
                model_probability=best_raw, regime_strength=0.8, market_quality=0.7,
                session="london", volatility=50.0, volatility_state="normal",
                engine_signal="SELL",
            )
        ).calibrated_value
    )

    return {
        "research_threshold": target,
        "matching_research_raw": round(best_raw, 6),
        "frozen_calibrated_equivalent": round(frozen_at_best, 6),
        "research_calibrated_at_raw": round(_research_cal(best_raw), 6),
        "mapping_error": round(best_diff, 6),
    }


def compute_threshold_equivalence(
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

    frozen_registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    frozen_range = getattr(frozen_registry.get("phase9_9"), "inner", None)
    frozen_trend = getattr(frozen_registry.get("trend_rf_v40"), "inner", None)
    research_range, research_trend = load_production_engines(window, symbol=symbol, seed=seed)

    frozen_method, _ = load_recovered_calibration(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=frozen_range, trend_engine=frozen_trend,
    )
    research_method, _ = load_recovered_calibration(
        window, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        range_engine=research_range, trend_engine=research_trend,
    )

    synthetic_equiv = _find_frozen_equivalent(
        research_method, frozen_method, target=RESEARCH_CALIB_THRESHOLD,
    )

    unified = build_unified_frame(window, dataset)
    orchestrator = DecisionOrchestrator()
    paired: list[dict[str, float]] = []

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx_f = build_market_context(
            row, symbol=symbol, timeframe="M5",
            range_engine=frozen_range, trend_engine=frozen_trend,
        )
        ctx_r = build_market_context(
            row, symbol=symbol, timeframe="M5",
            range_engine=research_range, trend_engine=research_trend,
        )
        dec_f = orchestrator.decide(ctx_f)
        dec_r = orchestrator.decide(ctx_r)
        from tradingbot.ml.confidence_engine.validator import raw_confidence_from_decision

        raw_f = raw_confidence_from_decision(dec_f, ctx_f)
        raw_r = raw_confidence_from_decision(dec_r, ctx_r)
        if str(raw_f.engine_signal) not in ("BUY", "SELL"):
            continue
        cal_f = float(frozen_method.calibrate(raw_f).calibrated_value)
        cal_r = float(research_method.calibrate(raw_r).calibrated_value)
        paired.append({"frozen": cal_f, "research": cal_r})

    empirical_equiv = RESEARCH_CALIB_THRESHOLD
    frozen_at_research_pass: list[float] = [
        p["frozen"] for p in paired if p["research"] >= RESEARCH_CALIB_THRESHOLD
    ]
    empirical_frozen_equiv = (
        round(min(frozen_at_research_pass), 6) if frozen_at_research_pass else None
    )

    return {
        "phase": "15G",
        "research_calibration_threshold": RESEARCH_CALIB_THRESHOLD,
        "synthetic_equivalence": synthetic_equiv,
        "empirical_pairs": len(paired),
        "empirical_frozen_threshold_when_research_passes": empirical_frozen_equiv,
        "interpretation": (
            f"Research {RESEARCH_CALIB_THRESHOLD} ≈ Frozen "
            f"{synthetic_equiv['frozen_calibrated_equivalent']} (synthetic Platt curve)"
            + (
                f"; empirical min frozen when research passes: {empirical_frozen_equiv}"
                if empirical_frozen_equiv is not None
                else ""
            )
        ),
    }
