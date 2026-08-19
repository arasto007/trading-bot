"""Phase 14.9 — multi-regime stability orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.validation import load_production_engines, validate_artifacts_unchanged
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_7.pipeline_runner import run_full_pipeline
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_9.config import (
    EXPECTED_FINGERPRINT,
    GRID_STRIDE,
    MAX_RESEARCH_BARS,
    MONTE_CARLO_SIMS,
    load_calibration_policy,
    phase14_9_final_report_path,
    phase14_9_reports_dir,
)
from tradingbot.ml.research.phase14_9.range_engine_analysis import analyze_range_engine
from tradingbot.ml.research.phase14_9.regime_performance_audit import audit_regime_performance
from tradingbot.ml.research.phase14_9.report_generator import build_final_report, write_report
from tradingbot.ml.research.phase14_9.robustness_validator import (
    run_monte_carlo,
    run_multi_period,
    run_walk_forward,
    validate_robustness,
)
from tradingbot.ml.research.phase14_9.trend_engine_stability import analyze_trend_stability
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase149Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def _prepare_candles(candles: pd.DataFrame, *, days: int) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    cutoff = c.index.max() - pd.Timedelta(days=days)
    c = c.loc[c.index >= cutoff].sort_index()
    if len(c) > MAX_RESEARCH_BARS:
        c = c.iloc[:: max(1, len(c) // MAX_RESEARCH_BARS)]
    return c


def run_phase14_9_stability(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase149Result:
    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset not found for {symbol} {timeframe}")

    fp_before = dataset_content_fingerprint(raw)
    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")

    quick_mode = quick if quick is not None else False
    primary = _prepare_candles(candles, days=days if not quick_mode else min(days, 90))

    range_engine, trend_engine = load_production_engines(primary, symbol=symbol, seed=seed)
    unified = build_unified_frame(primary, raw)
    cal_policy = load_calibration_policy(base_dir)
    cal_method, cal_meta = load_recovered_calibration(
        primary, raw, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        stride=GRID_STRIDE, range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )
    th = float(cal_meta.get("confidence_threshold", cal_policy["confidence_threshold"]))

    adaptive_records = run_adaptive_router_pipeline(
        primary, raw, cal_method, confidence_threshold=th,
        symbol=symbol, timeframe=timeframe, seed=seed, stride=GRID_STRIDE,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )
    static_records = run_full_pipeline(
        primary, raw, cal_method, confidence_threshold=th,
        symbol=symbol, timeframe=timeframe, seed=seed, stride=GRID_STRIDE,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )

    regime_audit = audit_regime_performance(adaptive_records)
    range_analysis = analyze_range_engine(
        primary, raw, symbol=symbol, seed=seed, stride=GRID_STRIDE,
        range_engine=range_engine, unified=unified, calibration_threshold=th,
    )
    trend_stability = analyze_trend_stability(
        candles, raw, symbol=symbol, timeframe=timeframe, seed=seed,
        base_dir=str(base_dir) if base_dir else None, quick=quick_mode,
    )

    walk_forward = run_walk_forward(
        primary, raw, cal_method, confidence_threshold=th,
        symbol=symbol, timeframe=timeframe, seed=seed, quick=quick_mode,
        range_engine=range_engine, trend_engine=trend_engine,
    )
    monte_carlo = run_monte_carlo(
        adaptive_records, simulations=100 if quick_mode else MONTE_CARLO_SIMS, seed=seed,
    )
    multi_period = run_multi_period(
        candles, raw, cal_method, confidence_threshold=th,
        symbol=symbol, timeframe=timeframe, seed=seed, quick=quick_mode,
        range_engine=range_engine, trend_engine=trend_engine,
    )
    robustness = validate_robustness(adaptive_records, walk_forward, monte_carlo, multi_period, stride=GRID_STRIDE)

    engine_comparison = {
        "phase": "14.9",
        "static_phase14": analyze_performance(static_records, stride=GRID_STRIDE),
        "adaptive_router": analyze_performance(adaptive_records, stride=GRID_STRIDE),
        "delta_trades": (
            analyze_performance(adaptive_records, stride=GRID_STRIDE).get("effective_trades_est", 0)
            - analyze_performance(static_records, stride=GRID_STRIDE).get("effective_trades_est", 0)
        ),
    }

    weight_stats = _router_weight_stats(adaptive_records)
    adaptive_results = {
        "phase": "14.9",
        "metrics": analyze_performance(adaptive_records, stride=GRID_STRIDE),
        "router_behavior": weight_stats,
        "regime_audit": regime_audit,
    }

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    fingerprint_ok = fp_before == fp_after
    artifacts = validate_artifacts_unchanged()

    final = build_final_report(
        regime_audit=regime_audit,
        range_analysis=range_analysis,
        trend_stability=trend_stability,
        robustness=robustness,
        engine_comparison=engine_comparison,
        adaptive_results=adaptive_results,
        fingerprint_unchanged=fingerprint_ok,
    )

    out = phase14_9_reports_dir(base_dir)
    reports = {
        "regime_breakdown": write_report(out / "regime_breakdown.json", regime_audit),
        "engine_comparison": write_report(out / "engine_comparison.json", engine_comparison),
        "adaptive_router_results": write_report(out / "adaptive_router_results.json", adaptive_results),
        "walk_forward": write_report(out / "walk_forward.json", walk_forward),
        "monte_carlo": write_report(out / "monte_carlo.json", monte_carlo),
    }

    final_payload = {
        **final,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "seed": seed,
        "dataset_fingerprint": fp_before,
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "fingerprint_unchanged": fingerprint_ok,
        "artifact_checksums": artifacts,
        "range_analysis": range_analysis,
        "trend_stability": trend_stability,
        "multi_period": multi_period,
        "quick_mode": quick_mode,
        "connected_to_live_trading": False,
    }
    reports["final_phase14_9_report"] = write_report(phase14_9_final_report_path(base_dir), final_payload)

    status = final["PHASE_14_9_STATUS"]
    if not fingerprint_ok:
        status = "NEEDS_REVIEW"

    return Phase149Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "adaptive_pf": engine_comparison["adaptive_router"].get("profit_factor"),
            "positive_periods": multi_period.get("positive_periods"),
            "walk_forward_robustness": walk_forward["robustness_score"],
            "monte_carlo_passes": monte_carlo.get("passes_gate"),
            "robustness_passes": robustness.get("passes"),
            "READY_FOR": final["READY_FOR"],
        },
    )


def _router_weight_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    tw = [float(r.get("trend_weight", 0)) for r in records]
    rw = [float(r.get("range_weight", 0)) for r in records]
    if not tw:
        return {}
    trend_selected = sum(1 for r in records if str(r.get("engine")) == "trend_rf_v40" and r.get("allowed"))
    range_selected = sum(1 for r in records if str(r.get("engine")) == "phase9_9" and r.get("allowed"))
    return {
        "mean_trend_weight": round(sum(tw) / len(tw), 4),
        "mean_range_weight": round(sum(rw) / len(rw), 4),
        "trend_selections_accepted": trend_selected,
        "range_selections_accepted": range_selected,
        "description": "Higher trend weight when ADX/slope elevated; range weight when ADX low and ATR compressed.",
    }
