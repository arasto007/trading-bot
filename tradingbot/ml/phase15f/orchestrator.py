"""Phase 15F — confidence recovery orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.domain.models import MarketKey
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.integration.recovered_calibration import calibration_status
from tradingbot.ml.phase15f.bundle_audit import validate_bundles
from tradingbot.ml.phase15f.confidence_trace import trace_confidence_flow
from tradingbot.ml.phase15f.config import DEFAULT_STRIDE, DEFAULT_WARMUP, RESEARCH_PROD_MAX_DIFF, reports_dir
from tradingbot.ml.phase15f.decision_policy_audit import audit_decision_policy
from tradingbot.ml.phase15f.pipeline_compare import compare_same_candle, replay_research_trades
from tradingbot.ml.phase15f.recovery_validator import run_recovery_validation
from tradingbot.ml.phase15f.report_generator import write_phase15f_reports


@dataclass
class Phase15FResult:
    status: str
    recommendation: str
    reports_dir: str
    primary_fix: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15F",
            "status": self.status,
            "recommendation": self.recommendation,
            "reports_dir": self.reports_dir,
            "primary_fix": self.primary_fix,
        }


def run_phase15f_recovery(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
    base_dir: str | Path | None = None,
    stride: int = DEFAULT_STRIDE,
    warmup: int = DEFAULT_WARMUP,
) -> Phase15FResult:
    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")

    market = MarketKey(symbol, timeframe)
    end_idx = len(candles) - 1
    slice_df = candles.iloc[max(0, end_idx - warmup) : end_idx + 1]

    confidence_flow = trace_confidence_flow(market=market, slice_df=slice_df, base_dir=str(base_dir) if base_dir else None)
    same_candle = compare_same_candle(
        market=market, slice_df=slice_df,
        base_dir=str(base_dir) if base_dir else None, seed=seed,
    )
    calibration_check = calibration_status(str(base_dir) if base_dir else None)
    calibration_check["pipeline_path"] = "Decision → Platt Calibration (14.6) → Risk → Quality → KernelAdapter"
    calibration_check["prior_production_path"] = "Decision → Heuristic 14.2A (no Platt) → Risk → Quality"
    bundle_validation = validate_bundles(base_dir=str(base_dir) if base_dir else None)
    policy_audit = audit_decision_policy(base_dir=str(base_dir) if base_dir else None)

    replay_rows: list[dict[str, Any]] = []
    if dataset is not None and not dataset.empty:
        replay_rows = replay_research_trades(
            candles=candles, dataset=dataset,
            base_dir=str(base_dir) if base_dir else None, max_trades=200, seed=seed,
            days=max(days, 365),
        )

    recovery_validation = run_recovery_validation(
        symbol=symbol, timeframe=timeframe,
        days_list=(days, min(365, days * 2)),
        base_dir=str(base_dir) if base_dir else None,
        stride=stride, warmup=warmup,
    )

    mean_diff = (
        sum(r["difference"] for r in replay_rows) / len(replay_rows) if replay_rows else 1.0
    )
    win_key = f"{days}d"
    win = recovery_validation.get("windows", {}).get(win_key, {})
    actionable = win.get("actionable_signals", 0)
    checksum_ok = recovery_validation.get("checksum_stable", False)

    primary_fix = "reconnect_phase14_6_platt_calibration"
    blockers: list[str] = []
    if actionable == 0:
        blockers.append("no_buy_sell_after_recovery")
    if mean_diff > RESEARCH_PROD_MAX_DIFF and replay_rows:
        blockers.append(f"research_prod_diff_{mean_diff:.4f}")
    if not checksum_ok:
        blockers.append("checksum_drift")

    recommendation = "READY_FOR_PHASE15G" if not blockers else "NEEDS_REVIEW"
    status = "PASS" if recommendation == "READY_FOR_PHASE15G" else "NEEDS_REVIEW"

    confidence_histogram = {
        "recovery_windows": recovery_validation.get("windows", {}),
        "replay_comparison": {
            "trades_compared": len(replay_rows),
            "mean_abs_diff": round(mean_diff, 6),
            "max_allowed_diff": RESEARCH_PROD_MAX_DIFF,
            "within_tolerance": mean_diff <= RESEARCH_PROD_MAX_DIFF,
        },
    }

    stages = confidence_flow.get("stages", {})
    final_report = {
        "phase": "15F",
        "status": status,
        "recommendation": recommendation,
        "shadow_mode_issue": True,
        "primary_bottleneck": "missing_platt_calibration_in_production_factory",
        "secondary_bottleneck": (
            "risk_gate_0.55_blocks_frozen_bundle_platt_output"
            if actionable == 0
            else None
        ),
        "stage_failing": (
            "risk_intelligence/confidence_risk_mapper.py"
            if actionable == 0 and stages.get("calibration_platt_action") in ("BUY", "SELL")
            else "calibration_14_2a"
        ),
        "fix_applied": primary_fix,
        "fix_module": "tradingbot/ml/integration/recovered_calibration.py",
        "fix_line_reference": "factory.build_ml_kernel_stack uses build_production_calibrated_adapter",
        "calibration_restored": calibration_check.get("production_uses_platt"),
        "platt_fit_uses_frozen_bundle_engines": True,
        "safe_to_enable_ml_live": recommendation == "READY_FOR_PHASE15G",
        "blockers": blockers,
        "confidence_flow_summary": confidence_flow.get("diagnosis", {}),
        "same_candle_diff": same_candle.get("differences", {}),
        "recovery_summary": win,
        "bundle_unchanged": bundle_validation.get("matches_phase15a_frozen"),
    }

    out = write_phase15f_reports(
        confidence_flow=confidence_flow,
        production_vs_research={"same_candle": same_candle, "replay_sample": replay_rows[:50]},
        calibration_check=calibration_check,
        bundle_validation=bundle_validation,
        decision_policy_audit=policy_audit,
        confidence_histogram=confidence_histogram,
        recovery_validation=recovery_validation,
        final_report=final_report,
        base_dir=base_dir,
    )

    return Phase15FResult(
        status=status,
        recommendation=recommendation,
        reports_dir=str(out),
        primary_fix=primary_fix,
    )
