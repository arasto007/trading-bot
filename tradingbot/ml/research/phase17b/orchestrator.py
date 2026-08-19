"""Phase 17B — offline RF+Top5 retrain lab orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, validate_trend_checksum
from tradingbot.ml.research.phase17b.acceptance import evaluate_acceptance
from tradingbot.ml.research.phase17b.compatibility import build_compatibility_report
from tradingbot.ml.research.phase17b.comparison import compare_models
from tradingbot.ml.research.phase17b.config import reports_dir
from tradingbot.ml.research.phase17b.dataset import build_dataset_report, build_feature_report, build_trend_dataset
from tradingbot.ml.research.phase17b.shadow_replay import run_shadow_replay
from tradingbot.ml.research.phase17b.training_lab import train_research_rf
from tradingbot.ml.research.phase17b.verdict import build_final_report, determine_verdict


def _write_json(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase17b_lab(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
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

    print("phase17b: building TREND dataset ...", flush=True)
    samples = build_trend_dataset(candles, symbol=symbol)
    dataset_report = build_dataset_report(samples)
    feature_report = build_feature_report(samples)

    print("phase17b: training research RF ...", flush=True)
    research, training_report = train_research_rf(samples)

    print("phase17b: model comparison ...", flush=True)
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    comparison, probability_analysis = compare_models(samples, bundle, research)

    print("phase17b: shadow replay (365d) ...", flush=True)
    shadow = run_shadow_replay(
        candles, dataset, research,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe, days=days, stride=stride,
    )

    acceptance = evaluate_acceptance(comparison, shadow, training_report)
    compatibility = build_compatibility_report()
    verdict = determine_verdict(acceptance, comparison)
    final = build_final_report(
        verdict=verdict,
        acceptance=acceptance,
        comparison=comparison,
        shadow=shadow,
        training=training_report,
        research_meta=research.to_dict(),
    )
    final["generated_at"] = datetime.now(timezone.utc).isoformat()
    final["checksum_unchanged"] = checksum_before.get("valid", False)

    checksum_after = validate_trend_checksum(base_dir=base_dir)
    final["production_checksum_after"] = checksum_after.get("valid", False)

    _write_json(out / "dataset_report.json", dataset_report)
    _write_json(out / "feature_report.json", feature_report)
    _write_json(out / "training_report.json", training_report)
    _write_json(out / "model_comparison.json", comparison)
    _write_json(out / "probability_analysis.json", probability_analysis)
    _write_json(out / "shadow_replay.json", shadow)
    _write_json(out / "acceptance_report.json", acceptance)
    _write_json(out / "compatibility_report.json", compatibility)
    _write_json(out / "phase17b_final_report.json", final)

    return {"verdict": verdict, "reports_dir": str(out), "final_report": final}
