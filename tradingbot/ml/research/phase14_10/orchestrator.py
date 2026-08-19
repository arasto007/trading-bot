"""Phase 14.10 — walk-forward stability recovery orchestrator."""

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
from tradingbot.ml.research.phase14_10.adaptive_regime_policy import research_regime_policy
from tradingbot.ml.research.phase14_10.adaptive_threshold_research import research_adaptive_threshold
from tradingbot.ml.research.phase14_10.config import (
    EXPECTED_FINGERPRINT,
    GRID_STRIDE,
    MAX_RESEARCH_BARS,
    WF_YEARS,
    load_calibration_policy,
    phase14_10_final_report_path,
    phase14_10_reports_dir,
)
from tradingbot.ml.research.phase14_10.montecarlo_per_year import run_montecarlo_per_year
from tradingbot.ml.research.phase14_10.regime_transition_analysis import analyze_regime_transitions
from tradingbot.ml.research.phase14_10.report_generator import (
    build_final_report,
    build_recommendations,
    write_report,
)
from tradingbot.ml.research.phase14_10.robustness_rebuilder import recompute_robustness
from tradingbot.ml.research.phase14_10.yearly_calibration_analysis import analyze_calibration_stability
from tradingbot.ml.research.phase14_10.yearly_confidence_distribution import analyze_confidence_distribution
from tradingbot.ml.research.phase14_10.yearly_feature_drift import analyze_feature_drift
from tradingbot.ml.research.phase14_10.yearly_performance import compute_yearly_metrics
from tradingbot.ml.research.phase14_10.yearly_regime_distribution import analyze_regime_distribution
from tradingbot.ml.research.phase14_10.yearly_threshold_analysis import analyze_yearly_thresholds
from tradingbot.ml.research.phase14_10.yearly_trade_distribution import analyze_trade_distribution
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase1410Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def _prepare_candles(candles: pd.DataFrame, *, days: int, quick: bool) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    if quick:
        cutoff = c.index.max() - pd.Timedelta(days=min(days, 90))
        c = c.loc[c.index >= cutoff].sort_index()
        if len(c) > MAX_RESEARCH_BARS:
            c = c.iloc[:: max(1, len(c) // MAX_RESEARCH_BARS)]
    else:
        wf_start = pd.Timestamp(f"{min(WF_YEARS)}-01-01", tz="UTC")
        wf_end = pd.Timestamp(f"{max(WF_YEARS)}-12-31 23:59:59", tz="UTC")
        c = c.loc[(c.index >= wf_start) & (c.index <= wf_end)].sort_index()
    return c


def run_phase14_10_stability(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
    baseline_robustness: float = 0.17,
) -> Phase1410Result:
    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset not found for {symbol} {timeframe}")

    fp_before = dataset_content_fingerprint(raw)
    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")

    quick_mode = quick if quick is not None else False
    primary = _prepare_candles(candles, days=days if not quick_mode else min(days, 90), quick=quick_mode)
    years = WF_YEARS[:2] if quick_mode else WF_YEARS
    stride = GRID_STRIDE
    mc_sims = 100 if quick_mode else 1000

    range_engine, trend_engine = load_production_engines(primary, symbol=symbol, seed=seed)
    unified = build_unified_frame(primary, raw)
    cal_policy = load_calibration_policy(base_dir)
    cal_method, cal_meta = load_recovered_calibration(
        primary, raw, base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
        stride=stride, range_engine=range_engine, trend_engine=trend_engine, unified=unified,
    )
    th = float(cal_meta.get("confidence_threshold", cal_policy["confidence_threshold"]))

    pipe_kw = dict(
        symbol=symbol, timeframe=timeframe, seed=seed, stride=stride,
        range_engine=range_engine, trend_engine=trend_engine, unified=unified,
        years=years,
    )

    yearly_metrics = compute_yearly_metrics(
        primary, raw, cal_method, confidence_threshold=th, **pipe_kw,
    )
    feature_drift = analyze_feature_drift(primary, raw, years=years)
    regime_distribution = analyze_regime_distribution(primary, raw, years=years)
    trade_distribution = analyze_trade_distribution(
        primary, raw, cal_method, confidence_threshold=th, **pipe_kw,
    )
    threshold_analysis = analyze_yearly_thresholds(primary, raw, cal_method, **pipe_kw)
    confidence_distribution = analyze_confidence_distribution(
        primary, raw, cal_method, confidence_threshold=th, **pipe_kw,
    )
    calibration_stability = analyze_calibration_stability(
        primary, raw, cal_method, confidence_threshold=th, **pipe_kw,
    )
    transition_analysis = analyze_regime_transitions(
        primary, raw, cal_method, confidence_threshold=th, **pipe_kw,
    )
    adaptive_threshold = research_adaptive_threshold(
        primary, raw, cal_method, regime_distribution, **pipe_kw,
    )
    adaptive_regime = research_regime_policy(primary, raw, cal_method, **pipe_kw)
    montecarlo_yearly = run_montecarlo_per_year(
        primary, raw, cal_method, confidence_threshold=th, simulations=mc_sims, **pipe_kw,
    )
    robustness_recovery = recompute_robustness(
        yearly_metrics, adaptive_threshold, adaptive_regime, baseline_robustness=baseline_robustness,
    )
    recommendations = build_recommendations(
        yearly_metrics=yearly_metrics,
        feature_drift=feature_drift,
        regime_distribution=regime_distribution,
        confidence_distribution=confidence_distribution,
        calibration_stability=calibration_stability,
        threshold_analysis=threshold_analysis,
        adaptive_threshold=adaptive_threshold,
        adaptive_regime_policy=adaptive_regime,
        transition_analysis=transition_analysis,
        robustness_recovery=robustness_recovery,
    )

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    fingerprint_ok = fp_before == fp_after
    artifacts = validate_artifacts_unchanged()

    final = build_final_report(
        yearly_metrics=yearly_metrics,
        feature_drift=feature_drift,
        regime_distribution=regime_distribution,
        confidence_distribution=confidence_distribution,
        calibration_stability=calibration_stability,
        threshold_analysis=threshold_analysis,
        adaptive_threshold=adaptive_threshold,
        adaptive_regime_policy=adaptive_regime,
        transition_analysis=transition_analysis,
        montecarlo_yearly=montecarlo_yearly,
        robustness_recovery=robustness_recovery,
        recommendations=recommendations,
        fingerprint_unchanged=fingerprint_ok,
        baseline_robustness=baseline_robustness,
    )

    out = phase14_10_reports_dir(base_dir)
    reports = {
        "yearly_metrics": write_report(out / "yearly_metrics.json", yearly_metrics),
        "feature_drift": write_report(out / "feature_drift.json", feature_drift),
        "regime_distribution": write_report(out / "regime_distribution.json", regime_distribution),
        "trade_distribution": write_report(out / "yearly_trade_distribution.json", trade_distribution),
        "confidence_distribution": write_report(out / "confidence_distribution.json", confidence_distribution),
        "calibration_stability": write_report(out / "calibration_stability.json", calibration_stability),
        "yearly_threshold_results": write_report(out / "yearly_threshold_results.json", threshold_analysis),
        "adaptive_threshold": write_report(out / "adaptive_threshold.json", adaptive_threshold),
        "transition_analysis": write_report(out / "transition_analysis.json", transition_analysis),
        "montecarlo_yearly": write_report(out / "montecarlo_yearly.json", montecarlo_yearly),
        "robustness_recovery": write_report(out / "robustness_recovery.json", robustness_recovery),
        "recommendations": write_report(out / "recommendations.json", recommendations),
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
        "trade_distribution": trade_distribution,
        "adaptive_regime_policy": adaptive_regime,
        "quick_mode": quick_mode,
        "full_dataset": not quick_mode,
        "stride": stride,
        "connected_to_live_trading": False,
    }
    reports["final_phase14_10_report"] = write_report(phase14_10_final_report_path(base_dir), final_payload)

    status = final["PHASE_14_10_STATUS"]
    if not fingerprint_ok:
        status = "NEEDS_REVIEW"

    return Phase1410Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "walk_forward_robustness_baseline": baseline_robustness,
            "walk_forward_robustness_updated": robustness_recovery.get("best_robustness"),
            "root_cause_ranking": recommendations.get("root_cause_ranking", []),
            "READY_FOR_PHASE15": final["READY_FOR_PHASE15"],
            "primary_recommendation": recommendations.get("primary_recommendation"),
        },
    )
