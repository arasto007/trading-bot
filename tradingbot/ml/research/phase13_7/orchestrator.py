"""Phase 13.7 — stability validation orchestrator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import (
    phase13_4_reports_dir,
    phase13_5_router_report_path,
    phase13_6_final_report_path,
    phase9_9_metadata_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase13_7.config import (
    EXPECTED_DATASET_FINGERPRINT,
    ROUTER_VARIANTS,
    phase13_7_final_report_path,
    phase13_7_reports_dir,
)
from tradingbot.ml.research.phase13_7.initial_audit import build_initial_audit
from tradingbot.ml.research.phase13_7.monte_carlo_validator import run_monte_carlo
from tradingbot.ml.research.phase13_7.range_failure_analyzer import analyze_range_failures
from tradingbot.ml.research.phase13_7.report_generator import (
    build_final_answers,
    build_robust_score_comparison,
    write_report,
)
from tradingbot.ml.research.phase13_7.router_recalibrator import run_router_backtest, variant_to_config
from tradingbot.ml.research.phase13_7.stability_optimizer import optimize_router_stability
from tradingbot.ml.research.phase13_7.trend_router_debugger import debug_trend_routing
from tradingbot.ml.research.phase13_7.walk_forward_validator import run_walk_forward_for_variant
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams, baseline_phase135_config
from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame, run_optimized_backtest


@dataclass
class Phase137Result:
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


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _metrics_row(label: str, metrics: dict[str, Any], *, robustness: float = 0.0) -> dict[str, Any]:
    return {
        "model": label,
        "trades": metrics.get("trades", 0),
        "profit_factor": metrics.get("profit_factor", 0.0),
        "expectancy": metrics.get("expectancy", metrics.get("expectancy_r", 0.0)),
        "win_rate": metrics.get("win_rate", 0.0),
        "max_drawdown": metrics.get("max_drawdown", 0.0),
        "robustness": robustness,
    }


def run_phase13_7_stability(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase137Result:
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

    merged = prepare_merged_frame(candles, raw)
    quick_mode = quick if quick is not None else len(merged) < 1_200
    cache = EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)

    initial_audit = build_initial_audit(base_dir)
    stability = optimize_router_stability(
        merged, candles, seed=seed, symbol=symbol, base_dir=base_dir, engine_cache=cache, quick=quick_mode
    )

    best_key = stability.get("best_variant") or "router_a"
    best_variant = next(v for v in ROUTER_VARIANTS if v.key == best_key)
    baseline_variant = ROUTER_VARIANTS[0]
    best_bt = run_router_backtest(
        merged, candles, best_variant, seed=seed, symbol=symbol, base_dir=base_dir, engine_cache=cache
    )
    best_wf = stability.get("walk_forward_by_variant", {}).get(best_key, {})
    wf_robustness = float(best_wf.get("robustness", {}).get("robustness_score", 0.0))

    trend_engine = cache.trend_engine(baseline_variant.trend_ml_threshold)
    trend_debug = debug_trend_routing(
        merged,
        candles,
        trend_engine=trend_engine,
        policy=baseline_variant.policy,
        min_confidence=baseline_variant.min_confidence,
    )

    range_failures = analyze_range_failures(best_bt["trades"])
    monte_carlo = run_monte_carlo(
        best_bt["trades"], simulations=100 if quick_mode else 1000, seed=seed
    )

    # Phase comparison table
    phase13_5 = _load_json(phase13_5_router_report_path(base_dir))
    phase13_6 = _load_json(phase13_6_final_report_path(base_dir))
    p99_cfg = OptimizerConfig(regime_params=RegimeThresholdParams(), policy="RANGE_ONLY", seed=seed, symbol=symbol)
    p135_cfg = baseline_phase135_config()
    p135_cfg = OptimizerConfig(**{**p135_cfg.__dict__, "symbol": symbol, "seed": seed})

    bt_99 = run_optimized_backtest(merged, candles, config=p99_cfg, base_dir=base_dir, engine_cache=cache)
    bt_135 = run_optimized_backtest(merged, candles, config=p135_cfg, base_dir=base_dir, engine_cache=cache)

    phase_comparison = [
        _metrics_row("Phase 9.9", bt_99["metrics"]),
        _metrics_row(
            "Phase 13.5 Router",
            phase13_5.get("combined_metrics", bt_135["metrics"]),
            robustness=0.5,
        ),
        _metrics_row(
            "Phase 13.6 Optimized",
            phase13_6.get("optimized_metrics", {}),
            robustness=float(phase13_6.get("robustness", {}).get("robustness_score", 0.0)),
        ),
        _metrics_row(
            "Phase 13.7 Best",
            best_bt["metrics"],
            robustness=wf_robustness,
        ),
    ]

    executed = [t for t in best_bt["trades"] if t.get("type") == "trade"]
    trend_trades = sum(1 for t in executed if t.get("source_engine") == "trend_ml")
    range_trades = sum(1 for t in executed if t.get("source_engine") == "phase9_9")
    baseline_executed = [
        t for t in run_router_backtest(
            merged, candles, baseline_variant, seed=seed, symbol=symbol, base_dir=base_dir, engine_cache=cache
        )["trades"]
        if t.get("type") == "trade"
    ]
    baseline_trend_trades = sum(1 for t in baseline_executed if t.get("source_engine") == "trend_ml")
    trend_contribution = {
        "best_variant_trend_trades": trend_trades,
        "best_variant_range_trades": range_trades,
        "baseline_router_a_trend_trades": baseline_trend_trades,
        "trend_pct_best": round(trend_trades / max(len(executed), 1) * 100, 2),
        "funnel_final_signals": trend_debug.get("funnel_answers", {}).get("5_reach_final_router", 0),
        "trend_measurable_in_baseline": baseline_trend_trades > 0,
    }

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    checksums_after = _artifact_checksums(base_dir)

    final_answers = build_final_answers(
        initial_audit=initial_audit,
        stability=stability,
        trend_debug=trend_debug,
        range_failures=range_failures,
        monte_carlo=monte_carlo,
        phase_comparison=phase_comparison,
        best_metrics=best_bt["metrics"],
        wf_robustness=wf_robustness,
        trend_contribution=trend_contribution,
    )
    recommendation = final_answers["PHASE_13_7_FINAL_REPORT"]["6_recommendation"]
    status = "PASS" if recommendation == "READY_FOR_PHASE14" else "NEEDS_REVIEW"
    if fp_before != fp_after or checksums_before != checksums_after:
        status = "NEEDS_REVIEW"

    out = phase13_7_reports_dir(base_dir)
    reports = {
        "initial_audit": write_report(out / "initial_audit.json", initial_audit),
        "robust_score_comparison": write_report(
            out / "robust_score_comparison.json", build_robust_score_comparison(stability)
        ),
        "trend_routing_debug": write_report(out / "trend_routing_debug.json", trend_debug),
        "range_failure_analysis": write_report(out / "range_failure_analysis.json", range_failures),
        "walk_forward_results": write_report(out / "walk_forward_results.json", best_wf),
        "monte_carlo_results": write_report(out / "monte_carlo_results.json", monte_carlo),
    }

    best_config_summary = {
        k: v
        for k, v in (stability.get("best_config") or {}).items()
        if k != "trades"
    }
    if "metrics" in best_config_summary:
        best_config_summary = {**best_config_summary, "metrics": best_bt["metrics"]}

    final_payload = {
        "phase": "13.7",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "dataset_fingerprint": fp_before,
        "expected_fingerprint": EXPECTED_DATASET_FINGERPRINT,
        "fingerprint_unchanged": fp_before == fp_after,
        "artifact_checksums": checksums_after,
        "artifacts_unchanged": checksums_before == checksums_after,
        "best_variant": best_key,
        "best_metrics": best_bt["metrics"],
        "best_config_summary": best_config_summary,
        "walk_forward_robustness": wf_robustness,
        "monte_carlo": monte_carlo,
        "trend_contribution": trend_contribution,
        "connected_to_live_trading": False,
        "quick_mode": quick_mode,
        **final_answers,
    }
    reports["final_phase13_7_report"] = write_report(phase13_7_final_report_path(base_dir), final_payload)

    return Phase137Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "best_variant": best_key,
            "best_pf": best_bt["metrics"].get("profit_factor"),
            "best_trades": best_bt["metrics"].get("trades"),
            "wf_robustness": wf_robustness,
            "recommendation": recommendation,
            "fingerprint_unchanged": fp_before == fp_after,
            "artifacts_unchanged": checksums_before == checksums_after,
        },
    )
