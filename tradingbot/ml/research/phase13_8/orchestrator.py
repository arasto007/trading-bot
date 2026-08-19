"""Phase 13.8 — trend recovery orchestrator."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase13_4_reports_dir,
    phase9_9_metadata_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase13_8.config import (
    EXPECTED_FINGERPRINT,
    MONTE_CARLO_SIMS,
    phase13_8_final_report_path,
    phase13_8_reports_dir,
)
from tradingbot.ml.research.phase13_8.monte_carlo import run_monte_carlo
from tradingbot.ml.research.phase13_8.recovered_trend_engine import RecoveredTrendEngine
from tradingbot.ml.research.phase13_8.report_generator import build_final_answers, write_report
from tradingbot.ml.research.phase13_8.router_simulator import simulate_routers
from tradingbot.ml.research.phase13_8.threshold_optimizer import optimize_threshold
from tradingbot.ml.research.phase13_8.trend_audit import build_trend_failure_audit
from tradingbot.ml.research.phase13_8.trend_comparator import compare_variants, run_variant_backtest
from tradingbot.ml.research.phase13_8.trend_feature_research import build_canonical_trend_frame
from tradingbot.ml.research.phase13_8.trend_label_v2 import build_labeled_samples, compare_labels
from tradingbot.ml.research.phase13_8.trend_ml_retrainer import fit_production_model, train_and_evaluate_models
from tradingbot.ml.research.phase13_8.trend_variants import VARIANTS
from tradingbot.ml.research.phase13_8.walk_forward import run_walk_forward
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams
from tradingbot.ml.research.router_optimizer.router_optimizer import run_optimized_backtest
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


@dataclass
class Phase138Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_checksums(base_dir: str | Path | None) -> dict[str, str | None]:
    trend_best = phase13_4_reports_dir(base_dir) / "trend_ml_best_model.json"
    if not trend_best.is_file():
        trend_best = phase13_4_reports_dir(None) / "trend_ml_best_model.json"
    return {
        "phase9_9_model": _sha256(phase9_9_model_path(None)),
        "phase9_9_scaler": _sha256(phase9_9_scaler_path(None)),
        "phase9_9_metadata": _sha256(phase9_9_metadata_path(None)),
        "phase13_4_trend_ml_best": _sha256(trend_best),
    }


def run_phase13_8_trend_recovery(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase138Result:
    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset v2 not found for {symbol} {timeframe}")

    fp_before = dataset_content_fingerprint(raw)
    checksums_before = _artifact_checksums(base_dir)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")
    if len(candles) > 25_000:
        candles = candles.iloc[:: max(1, len(candles) // 20_000)]

    quick_mode = quick if quick is not None else len(candles) < 1_200
    frame = build_canonical_trend_frame(candles)

    audit = build_trend_failure_audit(candles, raw, base_dir=base_dir)
    variant_results = compare_variants(frame, VARIANTS, symbol=symbol)

    best_variant_key = variant_results[0]["variant"] if variant_results else "variant_b"
    _, best_rule_fn = VARIANTS[best_variant_key]

    label_comparison = compare_labels(frame, symbol=symbol, rule_fn=best_rule_fn)
    best_label = label_comparison.get("best_label", "label_a_tp_before_sl")
    samples = build_labeled_samples(frame, symbol=symbol, rule_fn=best_rule_fn, label_key=best_label)

    ml_comparison = train_and_evaluate_models(samples, seed=seed, quick=quick_mode)
    best_model = ml_comparison.get("best_model") or "logistic"
    model, scaler, _ = fit_production_model(samples, model_name=best_model, seed=seed)

    wf_pre = run_walk_forward(frame, symbol=symbol, rule_fn=best_rule_fn, quick=quick_mode)
    threshold_results = optimize_threshold(
        frame,
        symbol=symbol,
        rule_fn=best_rule_fn,
        model=model,
        scaler=scaler,
        model_name=best_model,
        wf_score=wf_pre["robustness_score"],
    )
    best_threshold = float(threshold_results["best_threshold"])

    def ml_filter(row, direction: str) -> bool:
        ml = apply_trend_ml_filter(
            row, model=model, scaler=scaler, model_name=best_model, threshold=best_threshold
        )
        return bool(ml["allow_trade"])

    recovered_bt = run_variant_backtest(frame, symbol=symbol, rule_fn=best_rule_fn, ml_filter=ml_filter)
    wf_final = run_walk_forward(frame, symbol=symbol, rule_fn=best_rule_fn, ml_filter=ml_filter, quick=quick_mode)
    mc = run_monte_carlo(
        recovered_bt["trades"],
        simulations=100 if quick_mode else MONTE_CARLO_SIMS,
        seed=seed,
    )

    trend_engine = RecoveredTrendEngine(
        model=model,
        scaler=scaler,
        model_name=best_model,
        threshold=best_threshold,
        rule_fn=best_rule_fn,
        symbol=symbol,
    )
    cache = EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)
    router_comparison = simulate_routers(
        candles, raw, trend_engine=trend_engine, seed=seed, symbol=symbol, base_dir=base_dir, engine_cache=cache
    )

    p99_cfg = OptimizerConfig(regime_params=RegimeThresholdParams(), policy="RANGE_ONLY", seed=seed, symbol=symbol)
    from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame

    merged = prepare_merged_frame(candles, raw)
    bt_99 = run_optimized_backtest(merged, candles, config=p99_cfg, base_dir=base_dir, engine_cache=cache)
    phase99_pf = float(bt_99["metrics"].get("profit_factor", 0.0))

    trend_contribution = max((r.get("trend_contribution", 0) for r in router_comparison), default=0)
    final_answers = build_final_answers(
        audit=audit,
        best_variant=best_variant_key,
        best_label=best_label,
        best_model=best_model,
        best_threshold=best_threshold,
        trend_metrics=recovered_bt["metrics"],
        trend_contribution=trend_contribution,
        router_rows=router_comparison,
        wf_robustness=wf_final["robustness_score"],
        mc_positive=mc.get("remains_positive", False),
        phase99_pf=phase99_pf,
    )
    recommendation = final_answers["PHASE_13_8_FINAL_REPORT"]["decision"]
    status = "PASS" if recommendation == "READY_FOR_PHASE14" else "NEEDS_REVIEW"

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    checksums_after = _artifact_checksums(base_dir)
    if fp_before != fp_after or checksums_before != checksums_after:
        status = "NEEDS_REVIEW"

    out = phase13_8_reports_dir(base_dir)
    reports = {
        "trend_failure_audit": write_report(out / "trend_failure_audit.json", audit),
        "trend_variant_results": write_report(out / "trend_variant_results.json", {"ranking": variant_results}),
        "label_comparison": write_report(out / "label_comparison.json", label_comparison),
        "trend_ml_comparison": write_report(out / "trend_ml_comparison.json", ml_comparison),
        "threshold_results": write_report(out / "threshold_results.json", threshold_results),
        "monte_carlo_results": write_report(out / "monte_carlo_results.json", mc),
        "router_comparison": write_report(out / "router_comparison.json", {"routers": router_comparison}),
    }

    final_payload = {
        "phase": "13.8",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "dataset_fingerprint": fp_before,
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "fingerprint_unchanged": fp_before == fp_after,
        "artifacts_unchanged": checksums_before == checksums_after,
        "best_variant": best_variant_key,
        "best_label": best_label,
        "best_model": best_model,
        "best_threshold": best_threshold,
        "recovered_metrics": recovered_bt["metrics"],
        "walk_forward_robustness": wf_final["robustness_score"],
        "connected_to_live_trading": False,
        "quick_mode": quick_mode,
        **final_answers,
    }
    reports["final_phase13_8_report"] = write_report(phase13_8_final_report_path(base_dir), final_payload)

    return Phase138Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "best_variant": best_variant_key,
            "best_threshold": best_threshold,
            "recovered_trades": recovered_bt["metrics"].get("trades"),
            "recovered_pf": recovered_bt["metrics"].get("profit_factor"),
            "wf_robustness": wf_final["robustness_score"],
            "recommendation": recommendation,
            "fingerprint_unchanged": fp_before == fp_after,
        },
    )
