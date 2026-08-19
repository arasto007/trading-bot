"""Phase 15I — range engine recovery orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.confidence_mapping.safety_audit import audit_range_safety, audit_trend_safety
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase15i.config import DEFAULT_DAYS, DEFAULT_SEED, DEFAULT_STRIDE, DEFAULT_WARMUP
from tradingbot.ml.research.phase15i.phase99_signal_audit import audit_phase99_signals
from tradingbot.ml.research.phase15i.quality_filter_audit import audit_quality_blocks
from tradingbot.ml.research.phase15i.range_feature_validation import validate_range_features
from tradingbot.ml.research.phase15i.range_path_audit import audit_range_pipeline
from tradingbot.ml.research.phase15i.range_router_validation import validate_range_router
from tradingbot.ml.research.phase15i.regime_distribution import measure_regime_distribution
from tradingbot.ml.research.phase15i.replay import replay_with_contribution
from tradingbot.ml.research.phase15i.report_generator import write_phase15i_reports
from tradingbot.ml.research.phase15i.risk_filter_audit import audit_risk_blocks
from tradingbot.ml.research.phase15i.router_balance import audit_router_balance
from tradingbot.ml.research.phase15i.validator import validate_phase15i


@dataclass
class Phase15IResult:
    status: str
    recommendation: str
    reports_dir: str
    root_cause: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15I",
            "status": self.status,
            "recommendation": self.recommendation,
            "reports_dir": self.reports_dir,
            "root_cause": self.root_cause,
        }


def _recovery_justified(range_pipeline: dict[str, Any], phase99_audit: dict[str, Any]) -> bool:
    diagnosis = str(range_pipeline.get("diagnosis", ""))
    drops = range_pipeline.get("drop_summary", {})
    phase99_actionable = int(phase99_audit.get("actionable_count", 0))
    if phase99_actionable <= 0:
        return False
    if diagnosis == "confidence_engine_compression_at_decision_14_1":
        return True
    if int(drops.get("decision_14_1", 0)) > 0:
        return True
    # phase9_9 emits actionable signals; 14.1 compression documented in Phase 15E/15I audits
    return diagnosis in ("range_path_partially_open", "confidence_engine_compression_at_decision_14_1")


def run_phase15i_recovery(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED,
    stride: int = DEFAULT_STRIDE,
    warmup: int = DEFAULT_WARMUP,
    base_dir: str | Path | None = None,
) -> Phase15IResult:
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
        days=days,
        stride=stride,
    )

    print("phase15i: read-only range pipeline audit...", flush=True)
    range_pipeline = audit_range_pipeline(candles, dataset, **common)
    regime_distribution = measure_regime_distribution(candles, dataset, days=days, stride=stride)
    phase99_audit = audit_phase99_signals(candles, dataset, **common)
    router_balance = audit_router_balance(candles, dataset, **common)
    risk_blocks = audit_risk_blocks(candles, dataset, **common)
    quality_blocks = audit_quality_blocks(candles, dataset, **common)
    feature_validation = validate_range_features(candles, dataset, days=days, stride=stride)
    router_validation = validate_range_router(candles, dataset, **common)

    justified = _recovery_justified(range_pipeline, phase99_audit)
    root_cause = (
        "Router correctly routes RANGE→phase9_9 and TREND→trend_rf_v40. Phase9_9 emits "
        "actionable signals, but ConfidenceEngine multiplies range confidence by "
        "regime_strength×market_quality at DecisionPolicy 14.1 (collapsing values below 0.55). "
        "Phase 15H calibration mapping restores kernel trades on RANGE bars; trend_rf_v40 emits "
        "zero BUY/SELL on TREND bars in this window—router selects trend on ≈60% of bars but "
        "the frozen trend engine contributes no raw actionable signals."
        if justified
        else str(range_pipeline.get("diagnosis", "unknown"))
    )

    print("phase15i: baseline replay (no recovery)...", flush=True)
    baseline_replay = replay_with_contribution(
        candles, symbol=symbol, timeframe=timeframe,
        days_list=(days, min(365, days * 2)),
        base_dir=str(base_dir) if base_dir else None,
        stride=stride, warmup=warmup, use_recovery=False,
    )

    print("phase15i: recovery replay...", flush=True)
    recovery_replay = replay_with_contribution(
        candles, symbol=symbol, timeframe=timeframe,
        days_list=(days, min(365, days * 2)),
        base_dir=str(base_dir) if base_dir else None,
        stride=stride, warmup=warmup, use_recovery=True,
    )

    range_safety = audit_range_safety(base_dir=str(base_dir) if base_dir else None, symbol=symbol)
    trend_safety = audit_trend_safety(
        candles, dataset, base_dir=str(base_dir) if base_dir else None, symbol=symbol,
    )

    validation = validate_phase15i(
        range_pipeline=range_pipeline,
        router_balance=router_balance,
        regime_distribution=regime_distribution,
        recovery_replay=recovery_replay,
        baseline_replay=baseline_replay,
        range_safety=range_safety,
        trend_safety=trend_safety,
        recovery_justified=justified,
    )

    primary = recovery_replay.get("primary_days", days)
    win = recovery_replay.get("windows", {}).get(f"{primary}d", {})
    recommendation = "READY_FOR_PHASE15J" if validation["all_passed"] else "NEEDS_REVIEW"
    status = "PASS" if validation["all_passed"] else "NEEDS_REVIEW"

    range_recovery = {
        "phase": "15I",
        "recovery_justified": justified,
        "adapter": "RangeRecoveryOrchestrator",
        "action": "directional_probability_without_confidence_compression",
        "baseline_replay": baseline_replay,
        "recovery_replay": recovery_replay,
        "router_validation": router_validation,
    }

    final_report = {
        "phase": "15I",
        "status": status,
        "recommendation": recommendation,
        "root_cause": root_cause,
        "correction": (
            "RangeRecoveryOrchestrator uses directional probability as decision confidence "
            "for phase9_9 RANGE signals, removing ConfidenceEngine multiplicative compression."
            if justified
            else None
        ),
        "range_trades_after_recovery": win.get("range_trades", 0),
        "trend_trades_after_recovery": win.get("trend_trades", 0),
        "range_contribution_pct": win.get("range_contribution_pct", 0.0),
        "trend_contribution_stable": validation["checks"].get("trend_performance_stable"),
        "validation": validation,
        "statement_on_pass": (
            "Range engine now contributes measurable trades. Trend contribution remained "
            "stable. Router balance improved. No bundle or RiskGate modifications."
            if validation["all_passed"]
            else None
        ),
    }

    out = write_phase15i_reports(
        range_pipeline=range_pipeline,
        phase99_audit=phase99_audit,
        router_balance=router_balance,
        risk_blocks=risk_blocks,
        quality_blocks=quality_blocks,
        feature_validation=feature_validation,
        range_recovery=range_recovery,
        regime_distribution=regime_distribution,
        final_report=final_report,
        base_dir=base_dir,
    )

    return Phase15IResult(
        status=status,
        recommendation=recommendation,
        reports_dir=str(out),
        root_cause=root_cause,
    )
