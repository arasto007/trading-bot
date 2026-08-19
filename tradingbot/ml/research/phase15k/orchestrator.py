"""Phase 15K — trend RF ceiling investigation orchestrator (read-only)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase15k.ceiling_analyzer import analyze_trend_ceiling
from tradingbot.ml.research.phase15k.config import DEFAULT_DAYS, DEFAULT_SEED, DEFAULT_STRIDE, HYPOTHESES
from tradingbot.ml.research.phase15k.data_access import Phase15KContext
from tradingbot.ml.research.phase15k.distribution_drift_ceiling import analyze_distribution_drift_ceiling
from tradingbot.ml.research.phase15k.engine_replay_trace import replay_engine_trace
from tradingbot.ml.research.phase15k.feature_ceiling_impact import analyze_feature_ceiling_impact
from tradingbot.ml.research.phase15k.model_behavior_simulator import simulate_model_behavior
from tradingbot.ml.research.phase15k.pipeline_injection_audit import audit_pipeline_injection
from tradingbot.ml.research.phase15k.recommendation_ceiling import build_ceiling_recommendation
from tradingbot.ml.research.phase15k.report_generator import write_phase15k_reports
from tradingbot.ml.research.phase15k.trend_ceiling_root_cause import detect_trend_ceiling_root_cause
from tradingbot.ml.research.phase15k.validator import validate_phase15k


@dataclass
class Phase15KResult:
    status: str
    root_cause: str
    evidence_score: float
    recommendation: str
    reports_dir: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15K",
            "status": self.status,
            "root_cause": self.root_cause,
            "evidence_score": self.evidence_score,
            "recommendation": self.recommendation,
            "reports_dir": self.reports_dir,
        }


def run_phase15k_ceiling_analysis(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED,
    stride: int = DEFAULT_STRIDE,
    base_dir: str | Path | None = None,
) -> Phase15KResult:
    _ = seed
    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    common = dict(base_dir=str(base_dir) if base_dir else None, days=days, stride=stride, symbol=symbol)

    print("phase15k: building shared context...", flush=True)
    ctx = Phase15KContext.build(candles, dataset, **common)

    print("phase15k: ceiling analyzer...", flush=True)
    ceiling = analyze_trend_ceiling(candles, dataset, **common, ctx=ctx)

    print("phase15k: feature impact...", flush=True)
    feature_impact = analyze_feature_ceiling_impact(candles, dataset, **common, ctx=ctx)

    print("phase15k: distribution drift...", flush=True)
    drift_kw = {**common, "stride": max(5, stride // 2)}
    distribution_drift = analyze_distribution_drift_ceiling(candles, dataset, **drift_kw, ctx=ctx)

    print("phase15k: model behavior simulation...", flush=True)
    model_behavior = simulate_model_behavior(candles, dataset, **common, ctx=ctx)

    print("phase15k: pipeline injection audit...", flush=True)
    pipeline_audit = audit_pipeline_injection(candles, dataset, **common)

    print("phase15k: engine replay trace...", flush=True)
    engine_replay = replay_engine_trace(candles, dataset, **common)

    root_cause = detect_trend_ceiling_root_cause(
        ceiling=ceiling,
        feature_impact=feature_impact,
        distribution_drift=distribution_drift,
        model_behavior=model_behavior,
        pipeline_audit=pipeline_audit,
        engine_replay=engine_replay,
    )
    recommendation = build_ceiling_recommendation(root_cause)

    validation = validate_phase15k(
        ceiling=ceiling,
        root_cause=root_cause,
        recommendation=recommendation,
        pipeline_audit=pipeline_audit,
        engine_replay=engine_replay,
    )

    status = "PASS" if validation["all_passed"] else "NEEDS_REVIEW"
    final_report = {
        "phase": "15K",
        "status": status,
        "read_only": True,
        "production_modified": False,
        "hypotheses_tested": list(HYPOTHESES),
        "root_cause": root_cause.get("root_cause"),
        "evidence_score": root_cause.get("evidence_score"),
        "top_contributing_factors": root_cause.get("top_contributing_factors"),
        "quantitative_proof": root_cause.get("quantitative_proof"),
        "recommended_action": recommendation.get("recommended_action"),
        "validation": validation,
        "mathematical_explanation": ceiling.get("mathematical_bound"),
        "statement_on_pass": (
            "Trend RF probability ceiling explained with quantitative evidence. "
            "No production modifications. Engine collapse at ML output stage confirmed."
            if validation["all_passed"]
            else None
        ),
    }

    out = write_phase15k_reports(
        trend_ceiling_analysis=ceiling,
        feature_ceiling_impact=feature_impact,
        distribution_drift_ceiling=distribution_drift,
        model_behavior_simulation=model_behavior,
        pipeline_injection_audit=pipeline_audit,
        engine_replay_trace=engine_replay,
        root_cause=root_cause,
        recommendation=recommendation,
        final_report=final_report,
        base_dir=base_dir,
    )

    return Phase15KResult(
        status=status,
        root_cause=str(root_cause.get("root_cause", "")),
        evidence_score=float(root_cause.get("evidence_score", 0.0)),
        recommendation=str(recommendation.get("recommended_action", "")),
        reports_dir=str(out),
    )
