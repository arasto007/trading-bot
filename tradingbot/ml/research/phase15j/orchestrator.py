"""Phase 15J — trend root cause orchestrator (read-only)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase15j.adapter_validation import validate_adapter_chain
from tradingbot.ml.research.phase15j.bundle_validation import validate_bundle
from tradingbot.ml.research.phase15j.config import DEFAULT_DAYS, DEFAULT_SEED, DEFAULT_STRIDE
from tradingbot.ml.research.phase15j.engine_probability_distribution import analyze_probability_distribution
from tradingbot.ml.research.phase15j.feature_drift import audit_feature_drift
from tradingbot.ml.research.phase15j.recommendation_engine import build_recommendation
from tradingbot.ml.research.phase15j.report_generator import write_phase15j_reports
from tradingbot.ml.research.phase15j.root_cause_detector import detect_root_cause
from tradingbot.ml.research.phase15j.stage_loss_report import build_stage_loss_report
from tradingbot.ml.research.phase15j.trend_pipeline_trace import trace_trend_pipeline
from tradingbot.ml.research.phase15j.trend_signal_statistics import compute_trend_statistics
from tradingbot.ml.research.phase15j.validator import validate_phase15j


@dataclass
class Phase15JResult:
    status: str
    root_cause: str
    primary_stop_stage: str
    reports_dir: str
    phase15k_focus: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15J",
            "status": self.status,
            "root_cause": self.root_cause,
            "primary_stop_stage": self.primary_stop_stage,
            "reports_dir": self.reports_dir,
            "phase15k_focus": self.phase15k_focus,
        }


def run_phase15j_rootcause(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED,
    stride: int = DEFAULT_STRIDE,
    base_dir: str | Path | None = None,
) -> Phase15JResult:
    _ = seed  # frozen bundle seed recorded in bundle_validation
    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    print("phase15j: bundle validation...", flush=True)
    bundle_validation = validate_bundle(base_dir=str(base_dir) if base_dir else None)

    print("phase15j: trend pipeline trace...", flush=True)
    trace_report = trace_trend_pipeline(
        candles, dataset,
        base_dir=str(base_dir) if base_dir else None,
        symbol=symbol, timeframe=timeframe, days=days, stride=stride,
    )

    print("phase15j: statistics & probability...", flush=True)
    trend_statistics = compute_trend_statistics(trace_report)
    probability_distribution = analyze_probability_distribution(
        candles, dataset, base_dir=str(base_dir) if base_dir else None,
        symbol=symbol, days=days, stride=stride,
    )

    print("phase15j: feature drift audit...", flush=True)
    feature_drift = audit_feature_drift(
        candles, dataset, base_dir=str(base_dir) if base_dir else None,
        symbol=symbol, days=days, stride=max(5, stride // 3),
    )

    print("phase15j: adapter validation...", flush=True)
    adapter_validation = validate_adapter_chain(
        candles, base_dir=str(base_dir) if base_dir else None,
        symbol=symbol, timeframe=timeframe,
    )

    stage_loss = build_stage_loss_report(trace_report, trend_statistics)
    root_cause = detect_root_cause(
        trace_report=trace_report,
        statistics=trend_statistics,
        probability=probability_distribution,
        feature_drift=feature_drift,
        stage_loss=stage_loss,
    )
    recommendation = build_recommendation(root_cause)

    validation = validate_phase15j(
        trace_report=trace_report,
        root_cause=root_cause,
        recommendation=recommendation,
        bundle_validation=bundle_validation,
        feature_drift=feature_drift,
    )

    status = "PASS" if validation["all_passed"] else "NEEDS_REVIEW"
    final_report = {
        "phase": "15J",
        "status": status,
        "read_only": True,
        "production_modified": False,
        "root_cause": root_cause.get("root_cause"),
        "primary_failing_stage": root_cause.get("primary_failing_stage"),
        "quantitative_summary": root_cause.get("quantitative_summary"),
        "validation": validation,
        "phase15k_should_investigate": recommendation.get("phase15k_investigation"),
        "recommendation_statement": recommendation.get("statement"),
        "statement_on_pass": (
            "Exact first failing stage identified with quantitative evidence. "
            "No production components modified. Phase15K investigation scope defined."
            if validation["all_passed"]
            else None
        ),
    }

    out = write_phase15j_reports(
        trend_pipeline_trace=trace_report,
        trend_statistics=trend_statistics,
        probability_distribution=probability_distribution,
        feature_drift=feature_drift,
        bundle_validation=bundle_validation,
        adapter_validation=adapter_validation,
        stage_loss=stage_loss,
        root_cause=root_cause,
        recommendation=recommendation,
        final_report=final_report,
        base_dir=base_dir,
    )

    return Phase15JResult(
        status=status,
        root_cause=str(root_cause.get("root_cause", "")),
        primary_stop_stage=str(root_cause.get("primary_failing_stage", "")),
        reports_dir=str(out),
        phase15k_focus=str(recommendation.get("phase15k_investigation", "")),
    )
