"""Phase 22I — decision engine hold profiling on Dataset A."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from tradingbot.ml.research.phase22f.config import RapidDataset


def _hold_reason(
    *,
    regime: str,
    engine_id: str | None,
    raw_action: str,
    final_action: str,
    model_conf: float,
    final_conf: float,
    policy_threshold: float,
    range_signal: str,
    range_prob: float,
    trend_signal: str,
    trend_prob: float,
) -> str:
    if regime in ("NO_TRADE", "HIGH_VOLATILITY"):
        return f"blocked_regime:{regime}"
    if engine_id is None:
        return "no_engine_selected"
    if raw_action not in ("BUY", "SELL"):
        if engine_id == "phase9_9" and 0.45 <= range_prob <= 0.55:
            return "engine_hold:range_prob_dead_zone"
        if range_signal in ("BUY", "SELL") and raw_action == "HOLD":
            return "engine_hold:range_threshold"
        if trend_signal in ("BUY", "SELL") and raw_action == "HOLD":
            return "engine_hold:trend_rules_or_ml"
        return "engine_hold:other"
    if final_action == "HOLD" and raw_action in ("BUY", "SELL"):
        if final_conf < policy_threshold:
            return "policy_confidence_gate"
        return "policy_other"
    return "passed"


async def profile_decision_holds(
    dataset: RapidDataset,
    *,
    timeframe: str = "M5",
    stride: int = 5,
    warmup: int = 300,
) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.research.phase22f.config import configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset

    configure_research_env()
    PipelineCache.reset()
    legacy = load_legacy_config()
    base_dir = legacy.get("BASE_DIR")
    stack = build_ml_kernel_stack(base_dir=base_dir)
    orchestrator = stack.orchestrator
    inner = getattr(orchestrator, "inner", orchestrator)
    policy_threshold = float(inner.policy.min_confidence)

    frame = await load_ohlcv_for_dataset(dataset, timeframe)
    if frame is None or len(frame) < warmup + 10:
        return {"error": "no_data", "records": []}

    range_eng, trend_eng = PipelineCache.get_registry(base_dir=base_dir).get("phase9_9"), None
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    trend_eng = PipelineCache.get_registry(base_dir=base_dir).get(resolve_active_trend_engine_id())
    range_inner = getattr(range_eng, "inner", range_eng)
    trend_inner = getattr(trend_eng, "inner", trend_eng)

    records: list[dict] = []
    t0 = time.perf_counter()
    reason_counts: Counter[str] = Counter()
    regime_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()

    for i in range(warmup, len(frame), max(1, stride)):
        window = frame.iloc[: i + 1]
        ts = str(window.index[-1])
        try:
            unified = PipelineCache.get_unified_frame(
                window, base_dir=base_dir, symbol="XAUUSD", timeframe=timeframe,
            )
            if unified.empty:
                continue
            row = unified.iloc[-1]
            ctx = build_market_context(
                row, symbol="XAUUSD", timeframe=timeframe,
                range_engine=range_inner, trend_engine=trend_inner,
            )
            engine_id = select_engine(ctx.regime)
            selected = select_signal(ctx, engine_id)
            decision = orchestrator.decide(ctx)

            raw_action = str(selected.signal if selected else "HOLD")
            model_conf = float(selected.confidence if selected else 0.0)
            meta = decision.metadata or {}
            if meta.get("raw_engine_signal"):
                raw_action = str(meta["raw_engine_signal"])
                model_conf = float(meta.get("model_confidence", model_conf))

            final_conf = float(decision.confidence)
            final_action = str(decision.action)
            reason = _hold_reason(
                regime=ctx.regime,
                engine_id=engine_id,
                raw_action=raw_action,
                final_action=final_action,
                model_conf=model_conf,
                final_conf=final_conf,
                policy_threshold=policy_threshold,
                range_signal=str(ctx.range_signal.signal),
                range_prob=float(ctx.range_signal.probability),
                trend_signal=str(ctx.trend_signal.signal),
                trend_prob=float(ctx.trend_signal.probability),
            )
            reason_counts[reason] += 1
            regime_counts[ctx.regime] += 1
            action_counts[final_action] += 1

            records.append({
                "timestamp": ts,
                "bar_index": i,
                "regime": ctx.regime,
                "router_engine": engine_id,
                "range_signal": ctx.range_signal.signal,
                "range_prob": round(float(ctx.range_signal.probability), 4),
                "trend_signal": ctx.trend_signal.signal,
                "trend_prob": round(float(ctx.trend_signal.probability), 4),
                "raw_action": raw_action,
                "model_confidence": round(model_conf, 4),
                "final_confidence": round(final_conf, 4),
                "policy_threshold": policy_threshold,
                "final_action": final_action,
                "hold_reason": reason,
                "explanation": decision.explanation[:4],
            })
        except Exception as exc:
            records.append({"timestamp": ts, "bar_index": i, "error": str(exc)})

    ok = [r for r in records if "error" not in r]
    total = max(len(ok), 1)
    passed = sum(1 for r in ok if r.get("hold_reason") == "passed")

    histogram = [
        {"reason": k, "count": v, "pct": round(v / total * 100, 2)}
        for k, v in reason_counts.most_common()
    ]

    return {
        "phase": "22I",
        "dataset": dataset.to_dict(),
        "timeframe": timeframe,
        "stride": stride,
        "bars_profiled": len(records),
        "bars_ok": len(ok),
        "policy_threshold": policy_threshold,
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "action_distribution": {k: round(v / total * 100, 2) for k, v in action_counts.items()},
        "regime_distribution": {k: round(v / total * 100, 2) for k, v in regime_counts.items()},
        "hold_histogram": histogram,
        "largest_hold_loss": histogram[0] if histogram else None,
        "actionable_rate_pct": round(passed / total * 100, 2),
        "records_sample": ok[:50],
    }
