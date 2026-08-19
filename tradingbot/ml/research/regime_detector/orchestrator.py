"""Phase 13.2 — regime detection research orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.regime_detector.regime_features import (
    compute_regime_features_from_candles,
    enrich_from_dataset,
)
from tradingbot.ml.research.regime_detector.regime_optimizer import feature_importance, optimize_regime_models
from tradingbot.ml.research.regime_detector.regime_report import build_regime_report, write_reports
from tradingbot.ml.research.regime_detector.regime_validator import validate_rule_baseline, walk_forward_validate
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


@dataclass
class Phase132Result:
    status: str
    best_model: str
    reports: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "best_model": self.best_model,
            "reports": self.reports,
            "summary": self.summary,
        }


def run_phase13_2_regime(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    base_dir: str | Path | None = None,
) -> Phase132Result:
    store = DatasetStore(base_dir)
    raw = store.load_v2(symbol, timeframe)
    if raw is None or raw.empty:
        raise FileNotFoundError(f"Dataset v2 not found for {symbol} {timeframe}")

    fingerprint_before = dataset_content_fingerprint(raw)
    reloaded = store.load_v2(symbol, timeframe)
    fingerprint_after = dataset_content_fingerprint(reloaded if reloaded is not None else raw)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is not None and not candles.empty:
        features = compute_regime_features_from_candles(candles)
        data_source = "candles"
    else:
        features = enrich_from_dataset(raw)
        data_source = "dataset_v2_features"

    if features.empty:
        raise RuntimeError("No regime features computed")

    if len(features) > 25_000:
        features = features.iloc[:: max(1, len(features) // 20_000)].reset_index(drop=True)

    baseline = validate_rule_baseline(features)
    comparison = optimize_regime_models(features, seed=seed)
    best = comparison["best_model"]

    best_wf = (
        walk_forward_validate(features, model_name=best, seed=seed)
        if best != "rule_baseline"
        else {"model": "rule_baseline", "windows": [], "mean_test_accuracy": None}
    )

    imp = feature_importance(features, seed=seed)
    confusion = {
        "labels": ["RANGE", "TREND", "HIGH_VOLATILITY", "NO_TRADE"],
        "windows": [
            {
                "window_id": w.get("window_id"),
                "matrix": w.get("confusion_matrix"),
            }
            for w in best_wf.get("windows", [])
            if not w.get("skipped")
        ],
    }

    regime_report = build_regime_report(
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        dataset_fingerprint=fingerprint_before,
        fingerprint_unchanged=fingerprint_before == fingerprint_after,
        feature_rows=len(features),
        baseline=baseline,
        best_model=best,
        validation_summary={
            "data_source": data_source,
            "best_walk_forward": best_wf,
            "model_comparison": comparison,
        },
    )

    paths = write_reports(
        regime_report=regime_report,
        confusion=confusion,
        feature_importance=imp,
        model_comparison=comparison,
        base_dir=base_dir,
    )

    checks = [
        baseline["distribution"].get("RANGE", 0) > 0,
        baseline["distribution"].get("TREND", 0) > 0,
        baseline["distribution"].get("HIGH_VOLATILITY", 0) > 0,
        fingerprint_before == fingerprint_after,
    ]
    status = "PASS" if all(checks) else "NEEDS_REVIEW"

    return Phase132Result(
        status=status,
        best_model=best,
        reports=paths,
        summary={
            "data_source": data_source,
            "feature_rows": len(features),
            "baseline_distribution": baseline["distribution"],
            "fingerprint_unchanged": fingerprint_before == fingerprint_after,
        },
    )
