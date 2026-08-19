"""Phase 14.6 — calibration recovery orchestrator."""

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
from tradingbot.ml.research.phase14_6.calibration_alternatives import build_calibration_method, compare_calibration_methods
from tradingbot.ml.research.phase14_6.calibration_audit import run_calibration_audit
from tradingbot.ml.research.phase14_6.config import (
    CALIBRATION_METHODS,
    EXPECTED_FINGERPRINT,
    GRID_STRIDE,
    MAX_RESEARCH_BARS,
    MONTE_CARLO_SIMS,
    phase14_6_final_report_path,
    phase14_6_reports_dir,
)
from tradingbot.ml.research.phase14_6.label_alignment import analyze_label_alignment
from tradingbot.ml.research.phase14_6.monte_carlo_validator import run_monte_carlo_validation
from tradingbot.ml.research.phase14_6.pipeline_runner import run_research_pipeline
from tradingbot.ml.research.phase14_6.report_generator import build_final_report, write_report
from tradingbot.ml.research.phase14_6.research_calibrator import build_calibration_samples
from tradingbot.ml.research.phase14_6.threshold_search import search_all_methods
from tradingbot.ml.research.phase14_6.walk_forward_validator import run_walk_forward_validation
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase146Result:
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


def run_phase14_6_recovery(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase146Result:
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

    audit = run_calibration_audit(
        candles,
        raw,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=stride,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )

    samples = build_calibration_samples(
        candles,
        raw,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=stride,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )
    method_names = CALIBRATION_METHODS[:2] if quick_mode else CALIBRATION_METHODS
    calibration_comparison = compare_calibration_methods(samples, methods=method_names)

    threshold_search = search_all_methods(
        candles,
        raw,
        method_names=method_names,
        samples_fit=samples,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=stride,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
        quick=quick_mode,
    )

    best_method = threshold_search["best_method"]
    best_result = threshold_search["best_threshold_result"] or {}
    best_th = float(best_result.get("confidence_threshold", 0.55))

    best_calibrator = build_calibration_method(best_method)
    best_calibrator.fit(samples)
    best_records = run_research_pipeline(
        candles,
        raw,
        calibration_method=best_calibrator,
        confidence_threshold=best_th,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=stride,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )
    bucket_analysis = analyze_label_alignment(best_records)

    walk_forward = run_walk_forward_validation(
        candles,
        raw,
        best_calibrator,
        confidence_threshold=best_th,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        quick=quick_mode,
        range_engine=range_engine,
        trend_engine=trend_engine,
    )
    monte_carlo = run_monte_carlo_validation(
        best_records,
        simulations=50 if quick_mode else MONTE_CARLO_SIMS,
        seed=seed,
    )

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    fingerprint_ok = fp_before == fp_after

    final = build_final_report(
        audit=audit,
        calibration_comparison=calibration_comparison,
        bucket_analysis=bucket_analysis,
        threshold_search=threshold_search,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        fingerprint_unchanged=fingerprint_ok,
        best_method=best_method,
        best_threshold=best_th,
        best_metrics=best_result,
    )

    out = phase14_6_reports_dir(base_dir)
    reports = {
        "confidence_audit": write_report(out / "confidence_audit.json", audit),
        "calibration_comparison": write_report(out / "calibration_comparison.json", calibration_comparison),
        "bucket_analysis": write_report(out / "bucket_analysis.json", bucket_analysis),
        "threshold_search": write_report(out / "threshold_search.json", threshold_search),
        "walk_forward_results": write_report(out / "walk_forward_results.json", walk_forward),
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
        "quick_mode": quick_mode,
        "compression_attribution": audit.get("compression_attribution"),
        "connected_to_live_trading": False,
    }
    reports["phase14_6_final_report"] = write_report(phase14_6_final_report_path(base_dir), final_payload)

    status = final["PHASE_14_6_STATUS"]
    if not fingerprint_ok:
        status = "NEEDS_REVIEW"

    return Phase146Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "best_calibration_method": best_method,
            "best_threshold": best_th,
            "compression_resolved": final["answers"]["1_compression_resolved"],
            "walk_forward_robustness": walk_forward["robustness_score"],
            "monte_carlo_passes": monte_carlo.get("passes_gate"),
            "READY_FOR": final["READY_FOR"],
        },
    )
