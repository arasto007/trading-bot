"""Phase 16C — TREND throughput root analysis orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase16c.config import reports_dir
from tradingbot.ml.research.phase16c.feature_importance import analyze_feature_importance
from tradingbot.ml.research.phase16c.funnel import build_trend_funnel
from tradingbot.ml.research.phase16c.pattern_analysis import analyze_rejection_patterns
from tradingbot.ml.research.phase16c.rejection_clusters import analyze_rejection_clusters
from tradingbot.ml.research.phase16c.rf_analysis import analyze_distance_to_threshold, analyze_rf_distribution
from tradingbot.ml.research.phase16c.rule_diagnostics import aggregate_rule_statistics
from tradingbot.ml.research.phase16c.threshold_simulation import build_throughput_analysis, simulate_thresholds
from tradingbot.ml.research.phase16c.verdict import build_final_report, determine_verdict


def _write_json(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase16c_analysis(
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

    print("phase16c: building TREND funnel ...", flush=True)
    funnel = build_trend_funnel(
        candles, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe,
        days=days, stride=stride,
    )
    records = funnel.pop("records")

    rule_stats = aggregate_rule_statistics(records)
    rf_dist = analyze_rf_distribution(records)
    distance = analyze_distance_to_threshold(records)
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
    feature_imp = analyze_feature_importance(records, bundle)
    clusters = analyze_rejection_clusters(records)
    patterns = analyze_rejection_patterns(records)
    threshold_sim = simulate_thresholds(records)
    throughput = build_throughput_analysis(funnel, rf_dist, rule_stats)
    verdict = determine_verdict(
        funnel=funnel, rule_stats=rule_stats, rf_dist=rf_dist,
        clusters=clusters, feature_imp=feature_imp, throughput=throughput,
    )
    final = build_final_report(
        verdict=verdict, funnel=funnel, rule_stats=rule_stats, rf_dist=rf_dist,
        clusters=clusters, throughput=throughput, threshold_sim=threshold_sim,
        symbol=symbol, timeframe=timeframe, days=days, stride=stride,
    )

    # Persist reports (strip heavy records from funnel file)
    funnel_report = {**funnel, "record_count": len(records)}
    _write_json(out / "trend_funnel.json", funnel_report)
    _write_json(out / "rule_statistics.json", rule_stats)
    _write_json(out / "rf_probability_distribution.json", rf_dist)
    _write_json(out / "distance_to_threshold.json", distance)
    _write_json(out / "feature_importance.json", feature_imp)
    _write_json(out / "rejection_clusters.json", clusters)
    _write_json(out / "pattern_analysis.json", patterns)
    _write_json(out / "throughput_analysis.json", throughput)
    final["generated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(out / "phase16c_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
    }
