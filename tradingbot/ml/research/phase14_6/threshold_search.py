"""Phase 14.6 — operating point threshold search."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationMethod, build_calibration_method
from tradingbot.ml.research.phase14_6.config import MIN_TRADE_FLOOR, THRESHOLD_GRID
from tradingbot.ml.research.phase14_6.pipeline_runner import pipeline_metrics, run_research_pipeline


def composite_threshold_score(
    metrics: dict[str, Any],
    *,
    wf_stability: float = 0.5,
    train_test_gap: float = 0.0,
) -> float:
    trades = int(metrics.get("effective_trades_est", metrics.get("trades", 0)))
    if trades < MIN_TRADE_FLOOR:
        return 0.0
    pf = min(float(metrics.get("profit_factor", 0)), 3.0) / 3.0
    exp = min(max(float(metrics.get("expectancy", 0)) + 1.0, 0.0), 2.0) / 2.0
    dd = 1.0 - min(float(metrics.get("max_drawdown", 1.0)), 1.0)
    stability = min(float(wf_stability), 1.0)
    trade_consistency = min(trades / 500.0, 1.0)
    raw = pf * 0.30 + exp * 0.25 + stability * 0.25 + dd * 0.10 + trade_consistency * 0.10
    return round(max(0.0, raw - min(train_test_gap, 0.4)), 4)


def search_operating_point(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method: CalibrationMethod,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
    quick: bool = False,
    wf_scores: dict[float, float] | None = None,
) -> dict[str, Any]:
    grid = THRESHOLD_GRID[:2] if quick else THRESHOLD_GRID
    wf = wf_scores or {}
    rows: list[dict[str, Any]] = []

    for threshold in grid:
        records = run_research_pipeline(
            candles,
            dataset,
            calibration_method=calibration_method,
            confidence_threshold=threshold,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            stride=stride,
            range_engine=range_engine,
            trend_engine=trend_engine,
            unified=unified,
        )
        metrics = pipeline_metrics(records, stride=stride)
        gap = abs(metrics.get("profit_factor", 0) - wf.get(threshold, metrics.get("profit_factor", 0))) * 0.1
        score = composite_threshold_score(metrics, wf_stability=wf.get(threshold, 0.5), train_test_gap=gap)
        rejected = metrics["effective_trades_est"] < MIN_TRADE_FLOOR
        rows.append(
            {
                "confidence_threshold": threshold,
                **metrics,
                "composite_score": score,
                "rejected": rejected,
                "train_test_gap_penalty": round(gap, 4),
            }
        )

    valid = [r for r in rows if not r["rejected"]]
    ranked = sorted(rows, key=lambda r: r["composite_score"], reverse=True)
    best = ranked[0] if ranked else (rows[0] if rows else None)
    return {
        "phase": "14.6",
        "calibration_method": getattr(calibration_method, "name", "unknown"),
        "grid": list(grid),
        "min_trade_floor": MIN_TRADE_FLOOR,
        "results": rows,
        "valid_count": len(valid),
        "best": best,
        "ranking": ranked,
    }


def search_all_methods(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    method_names: tuple[str, ...],
    samples_fit: list,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    from tradingbot.ml.research.phase14_6.calibration_alternatives import build_calibration_method

    per_method: dict[str, Any] = {}
    for name in method_names:
        method = build_calibration_method(name)
        method.fit(samples_fit)
        per_method[name] = search_operating_point(
            candles,
            dataset,
            method,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            stride=stride,
            range_engine=range_engine,
            trend_engine=trend_engine,
            unified=unified,
            quick=quick,
        )

    best_name = max(per_method.keys(), key=lambda k: per_method[k]["best"]["composite_score"] if per_method[k]["best"] else 0)
    return {
        "phase": "14.6",
        "per_method": per_method,
        "best_method": best_name,
        "best_threshold_result": per_method[best_name]["best"],
    }
