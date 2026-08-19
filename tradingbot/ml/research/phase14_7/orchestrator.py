"""Phase 14.7 — end-to-end pipeline validation orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.baseline_runner import run_baseline_pipeline
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase14_7.config import (
    EXPECTED_FINGERPRINT,
    GRID_STRIDE,
    MAX_RESEARCH_BARS,
    MONTE_CARLO_SIMS,
    PIPELINE_BASELINE,
    PIPELINE_FULL,
    PIPELINE_ROUTER,
    phase14_7_final_report_path,
    phase14_7_reports_dir,
)
from tradingbot.ml.research.phase14_7.engine_contribution import analyze_engine_contribution
from tradingbot.ml.research.phase14_7.monte_carlo_validator import run_monte_carlo_validation
from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance, compare_pipelines
from tradingbot.ml.research.phase14_7.pipeline_runner import run_full_pipeline
from tradingbot.ml.research.phase14_7.regime_analyzer import analyze_regimes, detect_regime_collapse
from tradingbot.ml.research.phase14_7.report_generator import build_final_report, write_report
from tradingbot.ml.research.phase14_7.router_runner import run_router_pipeline
from tradingbot.ml.research.phase14_7.walk_forward_validator import run_walk_forward_validation
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase147Result:
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


def run_phase14_7_validation(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase147Result:
    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset not found for {symbol} {timeframe}")

    fp_before = dataset_content_fingerprint(raw)
    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")

    candles = _prepare_candles(candles, days=days)
    quick_mode = quick if quick is not None else len(candles) < 2_000
    stride = GRID_STRIDE

    range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)
    unified = build_unified_frame(candles, raw)

    calibration_method, cal_policy = load_recovered_calibration(
        candles,
        raw,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=stride,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )
    confidence_threshold = float(cal_policy["confidence_threshold"])

    baseline_records = run_baseline_pipeline(
        candles, raw, symbol=symbol, timeframe=timeframe, seed=seed, stride=stride,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )
    router_records = run_router_pipeline(
        candles, raw, symbol=symbol, timeframe=timeframe, seed=seed, stride=stride,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )
    full_records = run_full_pipeline(
        candles, raw, calibration_method,
        confidence_threshold=confidence_threshold,
        symbol=symbol, timeframe=timeframe, seed=seed, stride=stride,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )

    baseline_metrics = analyze_performance(baseline_records, stride=stride)
    router_metrics = analyze_performance(router_records, stride=stride)
    full_metrics = analyze_performance(full_records, stride=stride)

    pipeline_results = {
        PIPELINE_BASELINE: baseline_metrics,
        PIPELINE_ROUTER: router_metrics,
        PIPELINE_FULL: full_metrics,
    }
    comparison = compare_pipelines(pipeline_results)
    baseline_comparison = {
        "phase": "14.7",
        "pipelines": pipeline_results,
        "comparison": comparison,
    }

    regime_results = analyze_regimes(full_records)
    regime_check = detect_regime_collapse(regime_results, max_dominance=0.85)
    engine_contribution = analyze_engine_contribution(baseline_records, router_records, full_records)

    walk_forward = run_walk_forward_validation(
        candles, raw, calibration_method,
        confidence_threshold=confidence_threshold,
        symbol=symbol, timeframe=timeframe, seed=seed, quick=quick_mode,
        range_engine=range_engine, trend_engine=trend_engine,
    )
    monte_carlo = run_monte_carlo_validation(
        full_records,
        simulations=50 if quick_mode else MONTE_CARLO_SIMS,
        seed=seed,
    )

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    fingerprint_ok = fp_before == fp_after

    final = build_final_report(
        comparison=comparison,
        full_metrics=full_metrics,
        regime_check=regime_check,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        fingerprint_unchanged=fingerprint_ok,
        calibration_policy=cal_policy,
    )

    out = phase14_7_reports_dir(base_dir)
    reports = {
        "baseline_comparison": write_report(out / "baseline_comparison.json", baseline_comparison),
        "full_pipeline_results": write_report(out / "full_pipeline_results.json", full_metrics),
        "regime_results": write_report(out / "regime_results.json", regime_results),
        "engine_contribution": write_report(out / "engine_contribution.json", engine_contribution),
        "walk_forward_results": write_report(out / "walk_forward_results.json", walk_forward),
        "monte_carlo_results": write_report(out / "monte_carlo_results.json", monte_carlo),
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
        "quick_mode": quick_mode,
        "regime_check": regime_check,
        "connected_to_live_trading": False,
    }
    reports["phase14_7_final_report"] = write_report(phase14_7_final_report_path(base_dir), final_payload)

    status = final["PHASE_14_7_STATUS"]
    if not fingerprint_ok:
        status = "NEEDS_REVIEW"

    return Phase147Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "baseline_pf": baseline_metrics["profit_factor"],
            "router_pf": router_metrics["profit_factor"],
            "full_pf": full_metrics["profit_factor"],
            "full_trades": full_metrics.get("effective_trades_est"),
            "walk_forward_robustness": walk_forward["robustness_score"],
            "monte_carlo_passes": monte_carlo.get("passes_gate"),
            "READY_FOR": final["READY_FOR"],
        },
    )
