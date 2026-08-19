"""Phase 22J — trend_rf_v41 engine forensics on Dataset A."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from tradingbot.ml.research.phase22f.config import RapidDataset


async def profile_trend_engine(
    dataset: RapidDataset,
    *,
    timeframe: str = "M5",
    stride: int = 5,
    warmup: int = 300,
) -> dict[str, Any]:
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id
    from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
    from tradingbot.ml.research.phase22f.config import configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row

    configure_research_env()
    PipelineCache.reset()
    legacy = load_legacy_config()
    base_dir = normalize_ml_base_dir(legacy.get("BASE_DIR"))
    trend_id = resolve_active_trend_engine_id()
    trend_wrapped = PipelineCache.get_registry(base_dir=base_dir).get(trend_id)
    trend_inner = getattr(trend_wrapped, "inner", trend_wrapped)
    threshold = float(getattr(trend_inner, "threshold", 0.4))

    frame = await load_ohlcv_for_dataset(dataset, timeframe)
    if frame is None or len(frame) < warmup + 10:
        return {"error": "no_data"}

    rule_fail: Counter[str] = Counter()
    ml_fail = 0
    actionable = 0
    trend_regime_bars = 0
    routed_non_trend = 0
    t0 = time.perf_counter()

    for i in range(warmup, len(frame), max(1, stride)):
        window = frame.iloc[: i + 1]
        unified = PipelineCache.get_unified_frame(
            window, base_dir=base_dir, symbol="XAUUSD", timeframe=timeframe,
        )
        if unified.empty:
            continue
        row = unified.iloc[-1]
        regime = rule_classify_row(row)
        if regime != "TREND":
            routed_non_trend += 1
            continue
        trend_regime_bars += 1

        direction = evaluate_variant_a(row, regime=regime)
        if direction == "HOLD":
            adx = float(row.get("adx", 0))
            if adx <= 25:
                rule_fail["adx_below_25"] += 1
            elif float(row.get("ema20", 0)) > float(row.get("ema50", 0)):
                rule_fail["buy_structure_fail"] += 1
            else:
                rule_fail["sell_structure_fail"] += 1
            continue

        try:
            ev = trend_inner.evaluate(row, regime=regime)
        except Exception as exc:
            rule_fail[f"evaluate_error:{type(exc).__name__}"] += 1
            continue

        if ev.get("signal") in ("BUY", "SELL"):
            actionable += 1
        else:
            prob = float(ev.get("probability", 0))
            if prob < threshold:
                ml_fail += 1
            else:
                rule_fail["ml_other_hold"] += 1

    total = max(trend_regime_bars, 1)
    return {
        "phase": "22J",
        "engine": trend_id,
        "dataset": dataset.to_dict(),
        "timeframe": timeframe,
        "stride": stride,
        "trend_regime_bars": trend_regime_bars,
        "routed_non_trend_while_scoring": routed_non_trend,
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "actionable_signals": actionable,
        "actionable_rate_pct": round(actionable / total * 100, 2),
        "rule_failure_breakdown": dict(rule_fail),
        "ml_threshold_failures": ml_fail,
        "ml_threshold": threshold,
        "rule_fn": "evaluate_variant_a",
        "bottleneck": _trend_bottleneck(rule_fail, ml_fail, trend_regime_bars, actionable),
    }


def _trend_bottleneck(rule_fail, ml_fail, total, actionable) -> dict[str, Any]:
    if total == 0:
        return {"primary": "routing", "detail": "No TREND regime bars"}
    rule_total = sum(rule_fail.values())
    if rule_total > total * 0.5:
        top = rule_fail.most_common(1)[0][0] if rule_fail else "unknown"
        return {"primary": "rule_bottleneck", "detail": top, "rule_fail_pct": round(rule_total / total * 100, 2)}
    if ml_fail > actionable:
        return {"primary": "ml_threshold", "detail": f"prob < threshold", "ml_fail_count": ml_fail}
    return {"primary": "routing", "detail": "TREND regime rare vs RANGE"}
