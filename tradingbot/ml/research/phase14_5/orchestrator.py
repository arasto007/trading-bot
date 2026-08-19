"""Phase 14.5 — confidence operating point orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase14_5.adaptive_threshold_optimizer import rank_thresholds, select_best_threshold
from tradingbot.ml.research.phase14_5.confidence_sweep import run_confidence_sweep
from tradingbot.ml.research.phase14_5.config import (
    EXPECTED_FINGERPRINT,
    MAX_RESEARCH_BARS,
    MONTE_CARLO_SIMS,
    phase14_5_final_report_path,
    phase14_5_reports_dir,
)
from tradingbot.ml.research.phase14_5.monte_carlo_validator import run_monte_carlo_validation
from tradingbot.ml.research.phase14_5.opportunity_analyzer import analyze_opportunities
from tradingbot.ml.research.phase14_5.pipeline_runner import RegimeConfidencePolicy, run_pipeline_with_policy
from tradingbot.ml.research.phase14_5.regime_threshold_optimizer import optimize_regime_thresholds
from tradingbot.ml.research.phase14_5.report_generator import build_final_report, write_report
from tradingbot.ml.research.phase14_5.walk_forward_validator import run_walk_forward_validation
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase145Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def _prepare_candles(
    candles: pd.DataFrame,
    *,
    days: int,
) -> pd.DataFrame:
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


def run_phase14_5_optimizer(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase145Result:
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

    range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)
    unified = build_unified_frame(candles, raw)

    sweep = run_confidence_sweep(
        candles,
        raw,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        quick=quick_mode,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )

    baseline_records = run_pipeline_with_policy(
        candles,
        raw,
        confidence_threshold=0.55,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=3,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )
    opportunity = analyze_opportunities(baseline_records)
    baseline_trades = sum(1 for r in baseline_records if r.get("allowed"))

    wf_scores: dict[float, float] = {}
    wf_candidates = sorted(
        sweep["results"],
        key=lambda r: r.get("effective_trades_est", 0),
        reverse=True,
    )[:3]
    for row in wf_candidates:
        th = float(row["confidence_threshold"])
        wf = run_walk_forward_validation(
            candles,
            raw,
            confidence_threshold=th,
            symbol=symbol,
            timeframe=timeframe,
            seed=seed,
            quick=quick_mode,
            range_engine=range_engine,
            trend_engine=trend_engine,
            unified=unified,
        )
        wf_scores[th] = float(wf["robustness_score"])
    for row in sweep["results"]:
        th = float(row["confidence_threshold"])
        if th not in wf_scores:
            wf_scores[th] = 0.35

    ranked = rank_thresholds(sweep["results"], wf_scores=wf_scores)
    best_fixed = select_best_threshold(sweep["results"], wf_scores=wf_scores)
    if best_fixed is None and ranked:
        best_fixed = ranked[0]
    if best_fixed is None and sweep["results"]:
        best_fixed = max(sweep["results"], key=lambda r: r.get("effective_trades_est", 0))

    best_th = float(best_fixed["confidence_threshold"]) if best_fixed else 0.55
    best_records = run_pipeline_with_policy(
        candles,
        raw,
        confidence_threshold=best_th,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=3,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )

    regime = optimize_regime_thresholds(
        candles,
        raw,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        quick=quick_mode,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )
    regime_policy = RegimeConfidencePolicy(thresholds=regime["regime_policy"])
    _ = run_pipeline_with_policy(
        candles,
        raw,
        regime_policy=regime_policy,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=3,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )

    walk_forward = run_walk_forward_validation(
        candles,
        raw,
        confidence_threshold=best_th,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        quick=quick_mode,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
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
        sweep=sweep,
        opportunity=opportunity,
        regime=regime,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        best_fixed=best_fixed,
        baseline_trades=baseline_trades,
        baseline_pf=4.0,
        fingerprint_unchanged=fingerprint_ok,
        records_best=best_records,
    )

    out = phase14_5_reports_dir(base_dir)
    reports = {
        "confidence_sweep": write_report(out / "confidence_sweep.json", sweep),
        "opportunity_analysis": write_report(out / "opportunity_analysis.json", opportunity),
        "regime_thresholds": write_report(out / "regime_thresholds.json", regime),
        "walk_forward_results": write_report(out / "walk_forward_results.json", walk_forward),
        "monte_carlo_results": write_report(out / "monte_carlo_results.json", monte_carlo),
    }
    if best_fixed:
        write_report(
            out / "best_confidence_policy.json",
            {
                "phase": "14.5",
                "policy_type": "fixed",
                "confidence_threshold": best_th,
                "composite_score": best_fixed.get("composite_score"),
                "metrics": best_fixed,
            },
        )

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
        "ranked_thresholds": ranked[:5],
        "regime_combined_metrics": regime.get("combined_metrics"),
        "connected_to_live_trading": False,
    }
    reports["final_phase14_5_report"] = write_report(phase14_5_final_report_path(base_dir), final_payload)
    write_report(out / "confidence_sweep_results.json", sweep)

    status = final["PHASE_14_5_STATUS"]
    if not fingerprint_ok:
        status = "NEEDS_REVIEW"

    return Phase145Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "best_confidence_threshold": best_th,
            "ranked_top": ranked[:3],
            "trades_recovered": final["answers"]["3_trades_recovered"],
            "walk_forward_robustness": walk_forward["robustness_score"],
            "monte_carlo_passes": monte_carlo.get("passes_gate"),
            "READY_FOR": final["READY_FOR"],
        },
    )
