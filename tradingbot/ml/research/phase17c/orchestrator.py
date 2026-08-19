"""Phase 17C — shadow bundle validation orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, validate_trend_checksum
from tradingbot.ml.research.phase17b.dataset import build_trend_dataset
from tradingbot.ml.research.phase17b.training_lab import train_research_rf
from tradingbot.ml.research.phase17c.config import reports_dir
from tradingbot.ml.research.phase17c.dual_shadow import run_dual_shadow_horizons
from tradingbot.ml.research.phase17c.monte_carlo import extract_research_returns, run_monte_carlo
from tradingbot.ml.research.phase17c.range_regression import evaluate_range_regression
from tradingbot.ml.research.phase17c.safety import evaluate_safety
from tradingbot.ml.research.phase17c.stability import evaluate_stability
from tradingbot.ml.research.phase17c.trend_quality import evaluate_trend_quality
from tradingbot.ml.research.phase17c.verdict import (
    build_checks,
    build_final_report,
    build_recommendation,
    determine_verdict,
)
from tradingbot.ml.research.phase17c.walk_forward import run_walk_forward


def _write_json(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase17c_validation(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    stride: int = 5,
    base_dir: str | None = None,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    checksum_before = validate_trend_checksum(base_dir=base_dir)

    print("phase17c: training research RF (offline) ...", flush=True)
    samples = build_trend_dataset(candles, symbol=symbol)
    research, _training = train_research_rf(samples)
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)

    print("phase17c: trend quality ...", flush=True)
    trend_quality = evaluate_trend_quality(samples, bundle, research)

    shadow = run_dual_shadow_horizons(
        candles, dataset, research,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe, stride=stride,
    )

    print("phase17c: walk-forward ...", flush=True)
    walk_forward = run_walk_forward(candles, dataset, bundle, research, stride=stride)

    print("phase17c: monte carlo ...", flush=True)
    returns = extract_research_returns(shadow)
    monte_carlo = run_monte_carlo(returns)

    range_reg = evaluate_range_regression(shadow)
    stability = evaluate_stability(
        research, bundle, samples, shadow, base_dir=base_dir,
    )
    checksum_after = validate_trend_checksum(base_dir=base_dir)
    safety = evaluate_safety(
        base_dir=base_dir,
        checksum_before=checksum_before,
        checksum_after=checksum_after,
    )

    checks = build_checks(
        shadow=shadow,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        range_reg=range_reg,
        trend_quality=trend_quality,
        stability=stability,
        safety=safety,
    )
    verdict = determine_verdict(
        shadow=shadow,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        range_reg=range_reg,
        trend_quality=trend_quality,
        stability=stability,
        safety=safety,
    )
    recommendation = build_recommendation(verdict, checks, shadow, trend_quality)
    final = build_final_report(
        verdict=verdict,
        checks=checks,
        recommendation=recommendation,
        shadow=shadow,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        range_reg=range_reg,
        trend_quality=trend_quality,
        stability=stability,
        safety=safety,
    )
    final["generated_at"] = datetime.now(timezone.utc).isoformat()

    _write_json(out / "shadow_comparison.json", shadow)
    _write_json(out / "walk_forward.json", walk_forward)
    _write_json(out / "monte_carlo.json", monte_carlo)
    _write_json(out / "trend_quality.json", trend_quality)
    _write_json(out / "range_regression.json", range_reg)
    _write_json(out / "stability.json", stability)
    _write_json(out / "safety.json", safety)
    _write_json(out / "recommendation.json", recommendation)
    _write_json(out / "phase17c_final_report.json", final)

    return {"verdict": verdict, "reports_dir": str(out), "final_report": final}
