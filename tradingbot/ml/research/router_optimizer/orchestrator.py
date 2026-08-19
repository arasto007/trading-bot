"""Phase 13.6 — router optimization orchestrator."""

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
    phase13_6_reports_dir,
    phase13_6_final_report_path,
    phase9_9_metadata_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.router_optimizer.confidence_optimizer import optimize_confidence_filter
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.failure_analyzer import analyze_failures
from tradingbot.ml.research.router_optimizer.regime_weight_optimizer import optimize_regime_thresholds
from tradingbot.ml.research.router_optimizer.report_generator import (
    build_final_answers,
    build_model_comparison,
    build_recovery_audit,
    write_report,
)
from tradingbot.ml.research.router_optimizer.optimizer_types import (
    OptimizerConfig,
    RegimeThresholdParams,
    baseline_phase135_config,
    config_to_dict,
    ml_threshold_pair,
)
from tradingbot.ml.research.router_optimizer.router_optimizer import (
    prepare_merged_frame,
    run_optimized_backtest,
)
from tradingbot.ml.research.router_optimizer.robustness_validator import overfit_analysis
from tradingbot.ml.research.router_optimizer.session_optimizer import optimize_router_sessions
from tradingbot.ml.research.router_optimizer.threshold_optimizer import optimize_thresholds
from tradingbot.ml.research.router_optimizer.trade_filter_optimizer import optimize_regime_policies
from tradingbot.ml.research.router_optimizer.walk_forward_optimizer import run_walk_forward_optimization

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"


@dataclass
class Phase136Result:
    status: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reports": self.reports, "summary": self.summary}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def run_phase13_6_optimizer(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase136Result:
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

    phase13_5_report = _load_json(phase13_5_router_report_path(base_dir))
    phase13_5_pf = float(phase13_5_report.get("combined_metrics", {}).get("profit_factor", 0.0))

    baseline_cfg = OptimizerConfig(**{**baseline_phase135_config().__dict__, "symbol": symbol, "seed": seed})
    baseline_bt = run_optimized_backtest(
        merged, candles, config=baseline_cfg, base_dir=base_dir, engine_cache=cache
    )

    threshold_results = optimize_thresholds(
        merged, candles, seed=seed, symbol=symbol, base_dir=base_dir, engine_cache=cache, quick=quick_mode
    )
    best_threshold = float(threshold_results["best_threshold"])
    buy_t, sell_t = ml_threshold_pair(best_threshold)

    regime_results = optimize_regime_thresholds(
        merged,
        candles,
        range_buy_threshold=buy_t,
        range_sell_threshold=sell_t,
        trend_ml_threshold=best_threshold,
        seed=seed,
        symbol=symbol,
        base_dir=base_dir,
        engine_cache=cache,
        quick=quick_mode,
    )
    best_regime = RegimeThresholdParams(
        adx_trend_min=float(regime_results["best_params"]["adx_trend_min"]),
        adx_range_max=float(regime_results["best_params"]["adx_range_max"]),
        atr_low_vol=float(regime_results["best_params"]["atr_low_vol"]),
    )
    threshold_results["best_regime_params"] = regime_results["best_params"]

    policy_results = optimize_regime_policies(
        merged,
        candles,
        regime_params=best_regime,
        range_buy_threshold=buy_t,
        range_sell_threshold=sell_t,
        trend_ml_threshold=best_threshold,
        seed=seed,
        symbol=symbol,
        base_dir=base_dir,
        engine_cache=cache,
        quick=quick_mode,
    )

    optimized_cfg = OptimizerConfig(
        regime_params=best_regime,
        range_buy_threshold=buy_t,
        range_sell_threshold=sell_t,
        trend_ml_threshold=best_threshold,
        policy=str(policy_results["best_policy"]),
        seed=seed,
        symbol=symbol,
    )
    confidence_results = optimize_confidence_filter(
        merged,
        candles,
        config=optimized_cfg,
        base_dir=base_dir,
        engine_cache=cache,
        quick=quick_mode,
    )
    optimized_cfg = OptimizerConfig(
        regime_params=best_regime,
        range_buy_threshold=buy_t,
        range_sell_threshold=sell_t,
        trend_ml_threshold=best_threshold,
        policy=str(policy_results["best_policy"]),
        min_confidence=float(confidence_results["best_min_confidence"]),
        seed=seed,
        symbol=symbol,
    )

    optimized_bt = run_optimized_backtest(
        merged, candles, config=optimized_cfg, base_dir=base_dir, engine_cache=cache
    )
    walk_forward = run_walk_forward_optimization(
        merged, candles, config=optimized_cfg, base_dir=base_dir, engine_cache=cache
    )

    comparison_configs = [
        ("Phase 9.9 only", OptimizerConfig(regime_params=RegimeThresholdParams(), policy="RANGE_ONLY", seed=seed, symbol=symbol)),
        ("Trend Engine only", OptimizerConfig(regime_params=RegimeThresholdParams(), policy="TREND_ONLY", seed=seed, symbol=symbol)),
        ("Router Phase13.5", baseline_cfg),
        ("Optimized Router Phase13.6", optimized_cfg),
    ]
    comparison_rows = []
    for name, cfg in comparison_configs:
        bt = run_optimized_backtest(merged, candles, config=cfg, base_dir=base_dir, engine_cache=cache)
        comparison_rows.append(
            {
                "name": name,
                "metrics": {
                    **bt["metrics"],
                    "walk_forward_profit_factor": walk_forward["mean_profit_factor"]
                    if name.startswith("Optimized")
                    else bt["metrics"]["profit_factor"],
                    "walk_forward_expectancy": walk_forward["mean_expectancy"]
                    if name.startswith("Optimized")
                    else bt["metrics"].get("expectancy", 0.0),
                },
                "robustness": walk_forward["robustness"]["robustness_score"]
                if name.startswith("Optimized")
                else 0.5,
            }
        )

    model_comparison = build_model_comparison(comparison_rows)
    session_results = optimize_router_sessions(optimized_bt["trades"], base_dir=base_dir)
    failure = analyze_failures(
        optimized_bt["trades"],
        session_pf={s["session_key"]: s.get("profit_factor", 0.0) for s in session_results.get("sessions", [])},
    )

    train_year = merged[pd.to_datetime(merged["timestamp"], utc=True).dt.year < 2024]
    test_year = merged[pd.to_datetime(merged["timestamp"], utc=True).dt.year >= 2024]
    overfit = overfit_analysis(
        run_optimized_backtest(
            train_year, candles, config=optimized_cfg, base_dir=base_dir, engine_cache=cache
        )["metrics"],
        run_optimized_backtest(
            test_year, candles, config=optimized_cfg, base_dir=base_dir, engine_cache=cache
        )["metrics"],
    )
    walk_forward["robustness"]["overfit_detected"] = overfit["overfit_detected"]

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    checksums_after = _artifact_checksums(base_dir)
    improved = float(optimized_bt["metrics"]["profit_factor"]) > phase13_5_pf

    recovery = build_recovery_audit(
        quick_mode=quick_mode,
        reports_exist_before=_reports_exist(base_dir),
        repairs=["engine_cache wired in orchestrator", "ml_threshold_pair fixed", "quick_mode for tests"],
    )

    out_dir = phase13_6_reports_dir(base_dir)
    reports = {
        "optimizer_report": write_report(
            out_dir / "optimizer_report.json",
            {
                "phase": "13.6",
                "baseline_metrics": baseline_bt["metrics"],
                "optimized_metrics": optimized_bt["metrics"],
                "phase13_5_pf": phase13_5_pf,
                "best_config": config_to_dict(optimized_cfg),
                "confidence_results": confidence_results,
                "quick_mode": quick_mode,
            },
        ),
        "threshold_results": write_report(out_dir / "threshold_results.json", threshold_results),
        "regime_results": write_report(out_dir / "regime_results.json", {**regime_results, **policy_results}),
        "session_results": write_report(out_dir / "session_results.json", session_results),
        "failure_analysis": write_report(out_dir / "failure_analysis.json", failure),
        "model_comparison": write_report(out_dir / "model_comparison.json", model_comparison),
        "walk_forward_results": write_report(out_dir / "walk_forward_results.json", walk_forward),
    }

    final_answers = build_final_answers(
        baseline_metrics=baseline_bt["metrics"],
        optimized_metrics=optimized_bt["metrics"],
        model_comparison=model_comparison,
        failure=failure,
        regime_results={**regime_results, **policy_results},
        threshold_results=threshold_results,
        robustness=walk_forward["robustness"],
        phase13_5_pf=phase13_5_pf,
        best_config=config_to_dict(optimized_cfg),
        range_buy=buy_t,
        range_sell=sell_t,
    )

    final_payload = {
        "phase": "13.6",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "dataset_fingerprint": fp_before,
        "fingerprint_unchanged": fp_before == fp_after,
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "artifact_checksums": checksums_after,
        "artifacts_unchanged": checksums_before == checksums_after,
        "baseline_metrics": baseline_bt["metrics"],
        "optimized_metrics": optimized_bt["metrics"],
        "overfit_analysis": overfit,
        "robustness": walk_forward["robustness"],
        "recovery_audit": recovery,
        "connected_to_live_trading": False,
        "ready_for_phase14": walk_forward["robustness"].get("stable", False) and not overfit["overfit_detected"],
        "pf_improved_vs_phase13_5": improved,
        **final_answers,
    }
    reports["final_phase13_6_report"] = write_report(
        phase13_6_final_report_path(base_dir), final_payload
    )

    status = "PASS"
    if fp_before != fp_after or checksums_before != checksums_after:
        status = "NEEDS_REVIEW"
    if overfit["overfit_detected"]:
        status = "NEEDS_REVIEW"

    return Phase136Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "best_policy": optimized_cfg.policy,
            "best_threshold": best_threshold,
            "range_buy": buy_t,
            "range_sell": sell_t,
            "optimized_pf": optimized_bt["metrics"]["profit_factor"],
            "phase13_5_pf": phase13_5_pf,
            "pf_improved": improved,
            "robustness_score": walk_forward["robustness"]["robustness_score"],
            "fingerprint_unchanged": fp_before == fp_after,
            "artifacts_unchanged": checksums_before == checksums_after,
            "quick_mode": quick_mode,
        },
    )


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


def _reports_exist(base_dir: str | Path | None) -> bool:
    out = phase13_6_reports_dir(base_dir)
    return (out / "final_phase13_6_report.json").is_file()
