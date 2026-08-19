"""Phase 14.8 — stress validation orchestrator."""

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
from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance
from tradingbot.ml.research.phase14_7.pipeline_runner import run_full_pipeline
from tradingbot.ml.research.phase14_7.router_runner import run_router_pipeline
from tradingbot.ml.research.phase14_8.confidence_audit import audit_confidence
from tradingbot.ml.research.phase14_8.config import (
    EXPECTED_FINGERPRINT,
    GRID_STRIDE,
    MONTE_CARLO_SIMS,
    phase14_8_final_report_path,
    phase14_8_reports_dir,
)
from tradingbot.ml.research.phase14_8.monte_carlo_extended import run_monte_carlo_extended
from tradingbot.ml.research.phase14_8.multi_period_validator import run_multi_period_validation, slice_candles
from tradingbot.ml.research.phase14_8.range_engine_audit import audit_range_engine
from tradingbot.ml.research.phase14_8.regime_stress_test import run_regime_stress_test
from tradingbot.ml.research.phase14_8.report_generator import build_final_report, write_report
from tradingbot.ml.research.phase14_8.risk_audit import audit_risk
from tradingbot.ml.research.phase14_8.stress_runner import run_scenario_stress, summarize_pipelines
from tradingbot.ml.research.phase14_8.stress_runner import build_atr_meta
from tradingbot.ml.research.phase14_8.trend_engine_audit import audit_trend_engine
from tradingbot.ml.research.phase14_8.walk_forward_extended import run_walk_forward_extended
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase148Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def run_phase14_8_stress_validation(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase148Result:
    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset not found for {symbol} {timeframe}")

    fp_before = dataset_content_fingerprint(raw)
    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")

    quick_mode = quick if quick is not None else False
    primary_candles = slice_candles(candles, days=days if not quick_mode else min(days, 90))

    range_engine, trend_engine = load_production_engines(primary_candles, symbol=symbol, seed=seed)
    unified = build_unified_frame(primary_candles, raw)
    atr_meta = build_atr_meta(unified)

    cal_method, cal_policy = load_recovered_calibration(
        primary_candles, raw, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        stride=GRID_STRIDE, range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )
    confidence_threshold = float(cal_policy["confidence_threshold"])

    baseline_records = run_baseline_pipeline(
        primary_candles, raw, symbol=symbol, timeframe=timeframe, seed=seed, stride=GRID_STRIDE,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )
    router_records = run_router_pipeline(
        primary_candles, raw, symbol=symbol, timeframe=timeframe, seed=seed, stride=GRID_STRIDE,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )
    full_records = run_full_pipeline(
        primary_candles, raw, cal_method, confidence_threshold=confidence_threshold,
        symbol=symbol, timeframe=timeframe, seed=seed, stride=GRID_STRIDE,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )

    full_metrics = analyze_performance(full_records, stride=GRID_STRIDE)
    stress_results = {
        "phase": "14.8",
        "primary_days": days,
        "pipelines": summarize_pipelines(baseline_records, router_records, full_records, stride=GRID_STRIDE),
        "scenarios": run_scenario_stress(
            baseline_records, router_records, full_records, atr_meta=atr_meta, stride=GRID_STRIDE
        )["scenarios"],
    }

    multi_period = run_multi_period_validation(
        candles, raw, symbol=symbol, timeframe=timeframe, seed=seed, base_dir=str(base_dir) if base_dir else None,
        range_engine=range_engine, trend_engine=trend_engine, quick=quick_mode,
    )

    walk_forward = run_walk_forward_extended(
        primary_candles, raw, cal_method, confidence_threshold=confidence_threshold,
        symbol=symbol, timeframe=timeframe, seed=seed, quick=quick_mode,
        range_engine=range_engine, trend_engine=trend_engine,
    )
    monte_carlo = run_monte_carlo_extended(
        full_records,
        simulations=100 if quick_mode else MONTE_CARLO_SIMS,
        seed=seed,
    )

    risk_audit_result = audit_risk(full_records)
    trend_audit_result = audit_trend_engine(full_records, walk_forward_windows=walk_forward.get("windows", []))
    range_audit_result = audit_range_engine(full_records, baseline_records)
    confidence_audit_result = audit_confidence(full_records)
    regime_stress = run_regime_stress_test(full_records)

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    fingerprint_ok = fp_before == fp_after

    final = build_final_report(
        multi_period=multi_period,
        regime_stress=regime_stress,
        risk_audit=risk_audit_result,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        fingerprint_unchanged=fingerprint_ok,
        full_metrics=full_metrics,
    )

    out = phase14_8_reports_dir(base_dir)
    reports = {
        "stress_results": write_report(out / "stress_results.json", stress_results),
        "risk_audit": write_report(out / "risk_audit.json", risk_audit_result),
        "trend_audit": write_report(out / "trend_audit.json", trend_audit_result),
        "range_audit": write_report(out / "range_audit.json", range_audit_result),
        "walk_forward_extended": write_report(out / "walk_forward_extended.json", walk_forward),
        "monte_carlo_extended": write_report(out / "monte_carlo_extended.json", monte_carlo),
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
        "confidence_audit": confidence_audit_result,
        "regime_stress": regime_stress,
        "multi_period": multi_period,
        "calibration_policy": cal_policy,
        "connected_to_live_trading": False,
    }
    reports["phase14_8_final_report"] = write_report(phase14_8_final_report_path(base_dir), final_payload)

    status = final["PHASE_14_8_STATUS"]
    if not fingerprint_ok:
        status = "NEEDS_REVIEW"

    return Phase148Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "full_pf": full_metrics["profit_factor"],
            "full_expectancy": full_metrics["expectancy"],
            "walk_forward_robustness": walk_forward["robustness_score"],
            "monte_carlo_passes": monte_carlo.get("passes_gate"),
            "risk_audit_passes": risk_audit_result.get("passes"),
            "positive_periods": multi_period.get("positive_periods"),
            "READY_FOR": final["READY_FOR"],
        },
    )
