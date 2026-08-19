"""Phase 13.10 — trend contribution expansion orchestrator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase13_4_reports_dir, phase9_9_metadata_path, phase9_9_model_path, phase9_9_scaler_path
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase13_10.config import EXPECTED_FINGERPRINT, phase13_10_final_report_path, phase13_10_reports_dir
from tradingbot.ml.research.phase13_10.monte_carlo import run_monte_carlo_phase13_10
from tradingbot.ml.research.phase13_10.report_generator import build_final_report, write_report
from tradingbot.ml.research.phase13_10.robust_score import count_trend_trades
from tradingbot.ml.research.phase13_10.router_policy import compare_router_policies
from tradingbot.ml.research.phase13_10.rule_comparator import compare_trend_rule_variants
from tradingbot.ml.research.phase13_10.threshold_optimizer import optimize_trend_threshold
from tradingbot.ml.research.phase13_10.trend_audit.funnel_analyzer import audit_trend_funnel
from tradingbot.ml.research.phase13_10.trend_engines import build_trend_adapter
from tradingbot.ml.research.phase13_10.walk_forward import run_expanding_walk_forward
from tradingbot.ml.research.phase13_8.trend_label_v2 import build_labeled_samples
from tradingbot.ml.research.phase13_8.trend_ml_retrainer import fit_production_model
from tradingbot.ml.research.phase13_8.trend_variants import VARIANTS, evaluate_variant_d
from tradingbot.ml.research.phase13_9.feature_parity_checker import check_feature_parity
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import run_unified_range_only, run_unified_router_backtest
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features

import pandas as pd


@dataclass
class Phase1310Result:
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


def _fit_trend_model(
    candles: pd.DataFrame,
    *,
    rule_fn,
    model_name: str,
    seed: int,
    symbol: str,
):
    import pandas as pd

    frame = build_ml_features(candles)
    samples = build_labeled_samples(frame, symbol=symbol, rule_fn=rule_fn, label_key="label_a_tp_before_sl")
    if samples.empty:
        return None, None, rule_fn
    model, scaler, _ = fit_production_model(samples, model_name=model_name, seed=seed)
    return model, scaler, rule_fn


def run_phase13_10_router_final(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase1310Result:
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
    cache = EngineCache(candles, symbol=symbol, seed=seed, base_dir=base_dir)

    p138_path = phase13_10_reports_dir(base_dir).parent / "phase13_8" / "final_phase13_8_report.json"
    if not p138_path.is_file():
        p138_path = Path("data/ml/reports/phase13_8/final_phase13_8_report.json")
    p138 = _load_json(p138_path)
    model_name = p138.get("best_model", "random_forest")
    baseline_threshold = float(p138.get("best_threshold", 0.45))

    # Determine best rule variant from 13.8 or default D
    best_variant_key = p138.get("best_variant", "variant_d")
    rule_fn = VARIANTS.get(best_variant_key, VARIANTS["variant_d"])[1]

    model, scaler, rule_fn = _fit_trend_model(
        candles, rule_fn=rule_fn, model_name=model_name, seed=seed, symbol=symbol
    )
    if model is None:
        rule_fn = evaluate_variant_d
        model, scaler, rule_fn = _fit_trend_model(
            candles, rule_fn=rule_fn, model_name=model_name, seed=seed, symbol=symbol
        )

    parity = check_feature_parity(candles, raw)
    unified = build_unified_frame(candles, raw)
    canonical = build_ml_features(candles)
    feature_drift = False
    for col in ("ema50_slope", "ema20", "adx", "breakout_distance"):
        if col in canonical.columns and col in unified.columns:
            n = min(len(canonical), len(unified))
            diff = (canonical[col].astype(float).iloc[:n] - unified[col].astype(float).iloc[:n]).abs().max()
            if float(diff) > 1e-4:
                feature_drift = True
                break

    # Task 1 — funnel audit
    funnel = audit_trend_funnel(
        candles,
        raw,
        rule_fn=rule_fn,
        model=model,
        scaler=scaler,
        model_name=model_name,
        threshold=baseline_threshold,
        policy="A",
    )

    # Task 2 — threshold optimization
    threshold_results = optimize_trend_threshold(
        candles,
        raw,
        model=model,
        scaler=scaler,
        model_name=model_name,
        rule_fn=rule_fn,
        seed=seed,
        symbol=symbol,
        base_dir=base_dir,
        engine_cache=cache,
        quick=quick_mode,
    )
    best_threshold = float(threshold_results.get("best_threshold") or baseline_threshold)

    # Task 3 — rule variant comparison
    rule_comparison = compare_trend_rule_variants(
        candles,
        raw,
        model=model,
        scaler=scaler,
        model_name=model_name,
        threshold=best_threshold,
        seed=seed,
        symbol=symbol,
        base_dir=base_dir,
        engine_cache=cache,
        quick=quick_mode,
    )
    if rule_comparison.get("best_variant"):
        best_variant_key = rule_comparison["best_variant"]
        rule_fn = VARIANTS[best_variant_key][1]

    # Task 4 — router policy comparison
    router_comparison = compare_router_policies(
        candles,
        raw,
        model=model,
        scaler=scaler,
        model_name=model_name,
        rule_fn=rule_fn,
        best_threshold=best_threshold,
        relaxed_threshold=0.30,
        seed=seed,
        symbol=symbol,
        base_dir=base_dir,
        engine_cache=cache,
        quick=quick_mode,
    )
    best_policy = router_comparison.get("best_policy", "router_a")

    # Build best router config for WF + MC
    policy_row = next((r for r in router_comparison["results"] if r["policy"] == best_policy), router_comparison["results"][0])
    relaxed = best_policy == "router_b"
    rules_only = best_policy == "router_c"
    range_only = best_policy == "router_d"
    threshold = 0.30 if relaxed else best_threshold

    if range_only:
        best_cfg = OptimizerConfig(regime_params=RegimeThresholdParams(), policy="RANGE_ONLY", seed=seed, symbol=symbol)
        best_adapter = None
        best_bt = run_unified_range_only(candles, raw, seed=seed, symbol=symbol, base_dir=base_dir)
    else:
        best_adapter = build_trend_adapter(
            model=model,
            scaler=scaler,
            model_name=model_name,
            threshold=threshold,
            rule_fn=rule_fn,
            symbol=symbol,
            rules_only=rules_only,
        )
        best_cfg = OptimizerConfig(
            regime_params=RegimeThresholdParams(),
            policy="A",
            trend_ml_threshold=threshold,
            seed=seed,
            symbol=symbol,
        )
        best_bt = run_unified_router_backtest(
            candles,
            raw,
            config=best_cfg,
            seed=seed,
            symbol=symbol,
            base_dir=base_dir,
            engine_cache=cache,
            trend_adapter=best_adapter,
        )

    bt_99 = run_unified_range_only(candles, raw, seed=seed, symbol=symbol, base_dir=base_dir)

    # Task 5 — walk forward
    walk_forward = run_expanding_walk_forward(
        candles,
        raw,
        config=best_cfg,
        trend_adapter=best_adapter,
        seed=seed,
        symbol=symbol,
        base_dir=base_dir,
        quick=quick_mode,
    )

    # Task 6 — Monte Carlo
    monte_carlo = run_monte_carlo_phase13_10(
        best_bt["trades"],
        simulations=50 if quick_mode else 1000,
        seed=seed,
    )

    # Update funnel with actual router trend trades
    funnel["funnel"]["router_executed_trend_trades"] = count_trend_trades(best_bt)

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    checksums_after = _artifact_checksums(base_dir)

    final_core = build_final_report(
        funnel=funnel,
        threshold_results=threshold_results,
        rule_comparison=rule_comparison,
        router_comparison=router_comparison,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        phase99_metrics=bt_99["metrics"],
        best_router_bt=best_bt,
        fingerprint_unchanged=fp_before == fp_after,
        artifacts_unchanged=checksums_before == checksums_after,
        feature_drift=feature_drift,
        best_policy_key=best_policy,
    )

    out = phase13_10_reports_dir(base_dir)
    reports = {
        "trend_funnel_report": write_report(out / "trend_funnel_report.json", funnel),
        "trend_threshold_results": write_report(out / "trend_threshold_results.json", threshold_results),
        "trend_rule_comparison": write_report(out / "trend_rule_comparison.json", rule_comparison),
        "router_policy_comparison": write_report(out / "router_policy_comparison.json", router_comparison),
        "walk_forward_phase13_10": write_report(out / "walk_forward_phase13_10.json", walk_forward),
        "monte_carlo_phase13_10": write_report(out / "monte_carlo_phase13_10.json", monte_carlo),
    }

    final_payload = {
        **final_core,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "dataset_fingerprint": fp_before,
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "fingerprint_unchanged": fp_before == fp_after,
        "artifacts_unchanged": checksums_before == checksums_after,
        "quick_mode": quick_mode,
        "connected_to_live_trading": False,
        "unified_frame_rows": len(build_unified_frame(candles, raw)),
        "best_policy_metrics": policy_row,
    }
    reports["final_phase13_10_report"] = write_report(phase13_10_final_report_path(base_dir), final_payload)

    status = final_core["status"]
    if fp_before != fp_after or checksums_before != checksums_after:
        status = "NEEDS_REVIEW"

    return Phase1310Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "trend_trades": count_trend_trades(best_bt),
            "router_pf": best_bt["metrics"].get("profit_factor"),
            "phase99_pf": bt_99["metrics"].get("profit_factor"),
            "best_threshold": best_threshold,
            "best_policy": best_policy,
            "walk_forward_robustness": walk_forward["robustness_score"],
            "monte_carlo_profitable_pct": monte_carlo["profitable_pct"],
            "ready_for_phase14": final_core["answers"]["5_ready_for_phase14"],
            "primary_bottleneck": funnel.get("primary_bottleneck"),
        },
    )
