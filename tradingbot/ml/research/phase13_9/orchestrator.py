"""Phase 13.9 — unified router orchestrator."""

from __future__ import annotations

import hashlib
import json
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
from tradingbot.ml.research.phase13_8.recovered_trend_engine import RecoveredTrendEngine
from tradingbot.ml.research.phase13_8.trend_ml_retrainer import fit_production_model
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_d
from tradingbot.ml.research.phase13_8.trend_label_v2 import build_labeled_samples
from tradingbot.ml.research.phase13_9.config import EXPECTED_FINGERPRINT, MONTE_CARLO_SIMS, phase13_9_final_report_path, phase13_9_reports_dir
from tradingbot.ml.research.phase13_9.feature_parity_checker import check_feature_parity
from tradingbot.ml.research.phase13_9.monte_carlo_validator import run_monte_carlo
from tradingbot.ml.research.phase13_9.report_generator import build_final_report, robust_score, write_report
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import run_unified_range_only, run_unified_router_backtest
from tradingbot.ml.research.phase13_9.signal_loss_analyzer import analyze_signal_loss
from tradingbot.ml.research.phase13_9.trend_adapter_validator import validate_trend_adapter
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase13_9.walk_forward_validator import run_walk_forward_unified
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams, baseline_phase135_config
from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame, run_optimized_backtest
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features


@dataclass
class Phase139Result:
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


def _metrics_row(label: str, metrics: dict[str, Any], *, wf: float = 0.0, trend_trades: int = 0) -> dict[str, Any]:
    return {
        "model": label,
        "trades": metrics.get("trades", 0),
        "profit_factor": metrics.get("profit_factor", 0.0),
        "expectancy": metrics.get("expectancy", metrics.get("expectancy_r", 0.0)),
        "win_rate": metrics.get("win_rate", 0.0),
        "max_drawdown": metrics.get("max_drawdown", 0.0),
        "walk_forward_score": wf,
        "monte_carlo_stable": None,
        "trend_contribution": trend_trades,
        "robust_score": robust_score(metrics, wf=wf),
    }


def run_phase13_9_unified_router(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
    quick: bool | None = None,
) -> Phase139Result:
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

    parity = check_feature_parity(candles, raw)
    signal_loss = analyze_signal_loss(candles, raw)
    trend_validation = validate_trend_adapter(candles, raw)

    # Phase 13.8 recovered trend engine (read-only artifacts, retrained in 13.8 research)
    frame = build_ml_features(candles)
    samples = build_labeled_samples(frame, symbol=symbol, rule_fn=evaluate_variant_d, label_key="label_a_tp_before_sl")
    p138_path = phase13_9_reports_dir(base_dir).parent / "phase13_8" / "final_phase13_8_report.json"
    if not p138_path.is_file():
        p138_path = Path("data/ml/reports/phase13_8/final_phase13_8_report.json")
    p138 = _load_json(p138_path)
    best_model = p138.get("best_model", "random_forest")
    best_threshold = float(p138.get("best_threshold", 0.45))
    if not samples.empty:
        model, scaler, _ = fit_production_model(samples, model_name=best_model, seed=seed)
    else:
        model, scaler = None, None

    recovered_trend = None
    if model is not None and scaler is not None:
        recovered_trend = RecoveredTrendEngine(
            model=model,
            scaler=scaler,
            model_name=best_model,
            threshold=best_threshold,
            rule_fn=evaluate_variant_d,
            symbol=symbol,
        )

    baseline_cfg = OptimizerConfig(**{**baseline_phase135_config().__dict__, "symbol": symbol, "seed": seed})

    # Comparisons
    bt_99 = run_unified_range_only(candles, raw, seed=seed, symbol=symbol, base_dir=base_dir)
    legacy_merged = prepare_merged_frame(candles, raw)
    bt_135 = run_optimized_backtest(legacy_merged, candles, config=baseline_cfg, base_dir=base_dir, engine_cache=cache)

    bt_138 = None
    if recovered_trend is not None:
        bt_138 = run_unified_router_backtest(
            candles, raw, config=baseline_cfg, seed=seed, symbol=symbol, base_dir=base_dir,
            engine_cache=cache, trend_adapter=recovered_trend,
        )

    bt_139 = run_unified_router_backtest(
        candles,
        raw,
        config=baseline_cfg,
        seed=seed,
        symbol=symbol,
        base_dir=base_dir,
        engine_cache=cache,
        trend_adapter=recovered_trend if recovered_trend is not None else cache.trend_engine(baseline_cfg.trend_ml_threshold),
    )

    wf_139 = run_walk_forward_unified(
        candles, raw, config=baseline_cfg, seed=seed, symbol=symbol, base_dir=base_dir, quick=quick_mode
    )
    mc_139 = run_monte_carlo(bt_139["trades"], simulations=100 if quick_mode else MONTE_CARLO_SIMS, seed=seed)

    def _trend_count(bt: dict[str, Any] | None) -> int:
        if not bt:
            return 0
        return sum(1 for t in bt["trades"] if t.get("type") == "trade" and t.get("source_engine") == "trend_ml")

    comparisons = [
        _metrics_row("Phase 9.9 only", bt_99["metrics"], wf=wf_139["robustness_score"]),
        _metrics_row("Phase 13.5 Router (legacy)", bt_135["metrics"], trend_trades=_trend_count(bt_135)),
        _metrics_row(
            "Phase 13.8 Recovered Trend",
            bt_138["metrics"] if bt_138 else {},
            trend_trades=_trend_count(bt_138),
        ),
        _metrics_row(
            "Phase 13.9 Unified Router",
            bt_139["metrics"],
            wf=wf_139["robustness_score"],
            trend_trades=_trend_count(bt_139),
        ),
    ]
    comparisons = [c for c in comparisons if c.get("trades") is not None]
    for c in comparisons:
        if c["model"] == "Phase 13.9 Unified Router":
            c["monte_carlo_stable"] = mc_139.get("remains_positive")

    best_router = max(comparisons, key=lambda r: r.get("robust_score", 0.0))["model"]
    trend_contribution = _trend_count(bt_139)

    final = build_final_report(
        parity=parity,
        signal_loss=signal_loss,
        trend_validation=trend_validation,
        comparisons=comparisons,
        best_router=best_router,
        wf_score=wf_139["robustness_score"],
        trend_contribution=trend_contribution,
    )

    reloaded = store.load_v2(symbol, timeframe)
    fp_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)
    checksums_after = _artifact_checksums(base_dir)

    status = "PASS" if final["ready_for_phase14"] else "NEEDS_REVIEW"
    if fp_before != fp_after or checksums_before != checksums_after:
        status = "NEEDS_REVIEW"

    out = phase13_9_reports_dir(base_dir)
    reports = {
        "feature_parity_report": write_report(out / "feature_parity_report.json", parity),
        "signal_loss_report": write_report(out / "signal_loss_report.json", signal_loss),
        "trend_validation": write_report(out / "trend_adapter_validation.json", trend_validation),
        "router_comparison": write_report(out / "router_comparison.json", {"comparisons": comparisons}),
        "walk_forward_results": write_report(out / "walk_forward_results.json", wf_139),
        "monte_carlo_results": write_report(out / "monte_carlo_results.json", mc_139),
    }

    final_payload = {
        "phase": "13.9",
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
        **final,
        "comparisons": comparisons,
    }
    reports["phase13_9_final_report"] = write_report(phase13_9_final_report_path(base_dir), final_payload)

    return Phase139Result(
        status=status,
        reports={k: str(v) for k, v in reports.items()},
        summary={
            "unified_signals": signal_loss.get("unified_signals"),
            "legacy_signals": signal_loss.get("legacy_signals"),
            "signal_preservation": final["signal_preservation"],
            "trend_contribution": trend_contribution,
            "best_router": best_router,
            "ready_for_phase14": final["ready_for_phase14"],
        },
    )
