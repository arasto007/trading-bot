"""Phase 15G — frozen bundle confidence analysis orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase15g.bundle_probability_audit import audit_bundle_probabilities
from tradingbot.ml.research.phase15g.confidence_ceiling import measure_confidence_ceiling
from tradingbot.ml.research.phase15g.confidence_recovery import build_recovery_recommendation
from tradingbot.ml.research.phase15g.config import DEFAULT_DAYS, DEFAULT_SEED, DEFAULT_STRIDE
from tradingbot.ml.research.phase15g.platt_curve_analysis import analyze_platt_curve
from tradingbot.ml.research.phase15g.production_replay import replay_production_pipeline
from tradingbot.ml.research.phase15g.report_generator import write_phase15g_reports
from tradingbot.ml.research.phase15g.research_vs_bundle import compare_research_vs_frozen
from tradingbot.ml.research.phase15g.risk_gate_simulator import simulate_risk_gate_thresholds
from tradingbot.ml.research.phase15g.threshold_equivalence import compute_threshold_equivalence
from tradingbot.ml.research.phase15g.validator import validate_phase15g_results


@dataclass
class Phase15GResult:
    status: str
    recommendation: str
    reports_dir: str
    root_cause: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15G",
            "status": self.status,
            "recommendation": self.recommendation,
            "reports_dir": self.reports_dir,
            "root_cause": self.root_cause,
        }


def run_phase15g_analysis(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED,
    stride: int = DEFAULT_STRIDE,
    base_dir: str | Path | None = None,
) -> Phase15GResult:
    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    common = dict(
        base_dir=str(base_dir) if base_dir else None,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        days=days,
        stride=stride,
    )

    bundle_audit = audit_bundle_probabilities(candles, dataset, **common)
    platt = analyze_platt_curve(candles, dataset, **common)
    ceiling = measure_confidence_ceiling(candles, dataset, **common)
    risk_sim = simulate_risk_gate_thresholds(candles, dataset, **common)
    research_vs = compare_research_vs_frozen(candles, dataset, **common)
    equivalence = compute_threshold_equivalence(candles, dataset, **common)
    prod_replay = replay_production_pipeline(
        candles, dataset,
        base_dir=str(base_dir) if base_dir else None,
        symbol=symbol,
        timeframe=timeframe,
        days=days,
        stride=max(stride, 10),
    )

    recovery = build_recovery_recommendation(
        ceiling=ceiling,
        bundle_audit=bundle_audit,
        research_vs=research_vs,
        platt=platt,
        equivalence=equivalence,
        risk_sim=risk_sim,
        production_replay=prod_replay,
    )

    validation = validate_phase15g_results(
        bundle_audit=bundle_audit,
        platt=platt,
        ceiling=ceiling,
        research_vs=research_vs,
        equivalence=equivalence,
        recovery=recovery,
    )

    root_cause = recovery.get("why_frozen_never_reaches_riskgate", "")
    if validation["all_passed"]:
        status = "PASS"
        recommendation = "READY_FOR_PHASE15H"
    else:
        status = "NEEDS_REVIEW"
        recommendation = "NEEDS_REVIEW"

    final_report = {
        "phase": "15G",
        "status": status,
        "recommendation": recommendation,
        "root_cause": root_cause,
        "why_frozen_never_reaches_riskgate": root_cause,
        "confidence_ceiling": ceiling.get("maximum_calibrated_confidence"),
        "risk_gate_requirement": ceiling.get("risk_gate_requirement"),
        "ceiling_below_risk_gate": ceiling.get("ceiling_below_risk_gate"),
        "frozen_compressed": bundle_audit.get("frozen_outputs_compressed"),
        "research_accepted_at_0_30": research_vs.get("research_accepted_at_cal_threshold"),
        "frozen_accepted_at_0_30": research_vs.get("frozen_accepted_at_cal_threshold"),
        "recovery_outcome": recovery.get("single_recommendation", {}).get("outcome"),
        "smallest_future_fix": recovery.get("smallest_future_fix"),
        "validation": validation,
        "production_replay": {
            "calibration_actionable": prod_replay.get("calibration_actionable"),
            "risk_quality_pass": prod_replay.get("risk_quality_pass"),
        },
    }

    out = write_phase15g_reports(
        bundle_probability=bundle_audit,
        platt_curve=platt,
        confidence_ceiling=ceiling,
        riskgate_simulation=risk_sim,
        research_vs_bundle=research_vs,
        threshold_equivalence=equivalence,
        recovery_recommendation=recovery,
        final_report=final_report,
        base_dir=base_dir,
    )

    return Phase15GResult(
        status=status,
        recommendation=recommendation,
        reports_dir=str(out),
        root_cause=root_cause,
    )
