"""Phase 22G — per-candle execution trace on Dataset A."""

from __future__ import annotations

import os
import time
from typing import Any

from tradingbot.ml.research.phase22f.config import RapidDataset


async def run_execution_trace(dataset: RapidDataset, *, stride: int = 3, timeframe: str = "M5") -> dict[str, Any]:
    os.environ["USE_ML_KERNEL"] = "true"
    os.environ["TREND_MODEL_VERSION"] = "v41"

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.phase19c.filters import apply_profitability_filters, load_filter_settings
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id
    from tradingbot.ml.decision_engine.strategy_selector import select_engine
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset

    PipelineCache.reset()
    legacy = load_legacy_config()
    base_dir = legacy.get("BASE_DIR")
    stack = build_ml_kernel_stack(base_dir=base_dir)
    deps = stack.as_dependencies(base_dir=base_dir)
    adapter = KernelAdapter(deps)

    frame = await load_ohlcv_for_dataset(dataset, timeframe)
    if frame is None or len(frame) < 100:
        return {"error": "no_data", "records": []}

    trend_id = resolve_active_trend_engine_id()
    records: list[dict] = []
    t0 = time.perf_counter()
    warmup = 300

    for i in range(warmup, len(frame), max(1, stride)):
        window = frame.iloc[: i + 1]
        ts = str(window.index[-1])
        market = MarketKey("XAUUSD", timeframe)

        try:
            range_inner, trend_inner = adapter._engine_inners()
            unified_frame = PipelineCache.get_unified_frame(
                window,
                base_dir=base_dir,
                symbol="XAUUSD",
                timeframe=timeframe,
            )
            if unified_frame.empty:
                records.append({"timestamp": ts, "bar_index": i, "error": "unified_frame_empty"})
                continue

            row = unified_frame.iloc[-1]
            ctx = build_market_context(
                row,
                symbol="XAUUSD",
                timeframe=timeframe,
                range_engine=range_inner,
                trend_engine=trend_inner,
            )
            regime = ctx.regime
            router_engine = select_engine(regime)

            calibrated, risk, quality = stack.quality.evaluate(ctx)
            raw_action = str(calibrated.decision.action)
            cal_action = str(calibrated.final_action)
            filt = None
            if cal_action in ("BUY", "SELL") and risk.allowed and quality.allowed:
                filt = apply_profitability_filters(row.to_dict(), settings=load_filter_settings())

            final = cal_action
            block_reason: list[str] = []
            if final not in ("BUY", "SELL"):
                block_reason.append("calibration_hold")
            if not risk.allowed:
                block_reason.append(f"risk:{getattr(risk, 'blocked_by', risk)}")
                final = "HOLD"
            if not quality.allowed:
                block_reason.append(f"quality:{getattr(quality, 'blocked_by', quality)}")
                final = "HOLD"
            if filt is not None and not filt.passed:
                block_reason.extend(list(filt.blocked_by))
                final = "HOLD"

            unified = adapter.produce_unified_signal(market, window)
            sig = adapter.generate_signal(market, window, config=legacy)
            exec_decision = "EXECUTE" if sig is not None else "NO_TRADE"

            records.append({
                "timestamp": ts,
                "bar_index": i,
                "regime": regime,
                "router_engine": router_engine,
                "active_trend_engine": trend_id,
                "executed_engine": unified.engine,
                "range_signal": ctx.range_signal.signal,
                "range_prob": round(float(ctx.range_signal.probability), 4),
                "trend_signal": ctx.trend_signal.signal,
                "trend_prob": round(float(ctx.trend_signal.probability), 4),
                "orchestrator_action": raw_action,
                "calibrated_action": cal_action,
                "calibrated_confidence": round(float(calibrated.final_confidence), 4),
                "risk_allowed": risk.allowed,
                "quality_allowed": quality.allowed,
                "quality_score": round(float(quality.score), 4) if hasattr(quality, "score") else None,
                "filters_passed": filt.passed if filt else None,
                "filters_blocked_by": list(filt.blocked_by) if filt and not filt.passed else [],
                "final_direction": final,
                "kernel_direction": unified.direction,
                "execution_decision": exec_decision,
                "block_reasons": block_reason,
                "reason": unified.reason[:5] if unified.reason else [],
            })
        except Exception as exc:
            records.append({"timestamp": ts, "bar_index": i, "error": str(exc)})

    ok = [r for r in records if "error" not in r]
    buy = sum(1 for r in ok if r.get("final_direction") == "BUY")
    sell = sum(1 for r in ok if r.get("final_direction") == "SELL")
    hold = sum(1 for r in ok if r.get("final_direction") not in ("BUY", "SELL"))
    execute = sum(1 for r in ok if r.get("execution_decision") == "EXECUTE")

    return {
        "phase": "22G",
        "dataset": dataset.to_dict(),
        "timeframe": timeframe,
        "stride": stride,
        "bars_traced": len(records),
        "bars_ok": len(ok),
        "bars_error": len(records) - len(ok),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "summary": {
            "buy_pct": round(buy / max(len(ok), 1) * 100, 2),
            "sell_pct": round(sell / max(len(ok), 1) * 100, 2),
            "hold_pct": round(hold / max(len(ok), 1) * 100, 2),
            "execute_count": execute,
        },
        "stage_block_counts": _stage_blocks(ok),
        "records": records,
    }


def _stage_blocks(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        if r.get("execution_decision") == "EXECUTE":
            continue
        for reason in r.get("block_reasons") or []:
            key = reason.split(":")[0] if ":" in reason else reason
            counts[key] = counts.get(key, 0) + 1
        if not r.get("block_reasons") and r.get("final_direction") == "HOLD":
            counts["engine_or_orchestrator_hold"] = counts.get("engine_or_orchestrator_hold", 0) + 1
    return counts
