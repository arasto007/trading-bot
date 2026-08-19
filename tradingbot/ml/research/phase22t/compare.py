"""Phase 22T — Dataset A signal-level comparison (range engine path)."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

import numpy as np

from tradingbot.ml.research.phase22f.config import RapidDataset, configure_research_env
from tradingbot.ml.research.phase22t.config import TIMEFRAME, use_live_phase99_features
from tradingbot.ml.research.phase22t.feature_source import compare_feature_sources
from tradingbot.ml.research.phase22t.patch import research_stack


async def profile_range_signals(
    dataset: RapidDataset,
    *,
    use_live: bool,
    base_dir: str | None,
    stride: int = 5,
    warmup: int = 300,
) -> dict[str, Any]:
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
    from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row

    configure_research_env()
    mode = "featurebuilder_live" if use_live else "current_repository"

    with research_stack(base_dir=base_dir, use_live=use_live) as stack:
        range_wrapped = stack.registry.get("phase9_9").inner

        frame = await load_ohlcv_for_dataset(dataset, TIMEFRAME)
        if frame is None or len(frame) < warmup + 10:
            return {"error": "no_data", "mode": mode}

        probs: list[float] = []
        signals: Counter[str] = Counter()
        engine_holds = 0
        feature_diff_bars = 0
        feature_samples: list[dict[str, Any]] = []
        range_bars = 0
        t0 = time.perf_counter()

        for i in range(warmup, len(frame), max(1, stride)):
            window = frame.iloc[: i + 1]
            unified = PipelineCache.get_unified_frame(
                window, base_dir=base_dir, symbol="XAUUSD", timeframe=TIMEFRAME,
            )
            if unified.empty:
                continue
            row = unified.iloc[-1]
            if rule_classify_row(row) != "RANGE":
                continue
            range_bars += 1

            if len(feature_samples) < 10:
                cmp = compare_feature_sources(
                    candles=window, unified_row=row, bar_index=len(window) - 1,
                    symbol="XAUUSD", base_dir=base_dir,
                )
                if cmp["any_diff"]:
                    feature_diff_bars += 1
                feature_samples.append({
                    "timestamp": str(row.get("timestamp")),
                    "merge": cmp["merge"],
                    "live": cmp["live"],
                    "abs_diff": cmp["abs_diff"],
                })

            ev = range_wrapped.evaluate(row=row_for_phase99_range(row))
            prob = float(ev.get("probability", 0.5))
            sig = str(ev.get("signal", "HOLD"))
            probs.append(prob)
            signals[sig] += 1
            if sig == "HOLD":
                engine_holds += 1

        arr = np.array(probs) if probs else np.array([0.5])
        scored = max(len(probs), 1)
        buy = signals.get("BUY", 0)
        sell = signals.get("SELL", 0)
        hold = signals.get("HOLD", 0)

        return {
            "mode": mode,
            "use_live_phase99": use_live,
            "dataset": dataset.to_dict(),
            "range_regime_bars": range_bars,
            "bars_scored": len(probs),
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "signals": {
                "BUY": buy,
                "SELL": sell,
                "HOLD": hold,
                "buy_pct": round(buy / scored * 100, 4),
                "sell_pct": round(sell / scored * 100, 4),
                "hold_pct": round(hold / scored * 100, 4),
            },
            "engine_hold": engine_holds,
            "signal_density_pct": round((buy + sell) / scored * 100, 4),
            "p_win": {
                "mean": round(float(arr.mean()), 6),
                "std": round(float(arr.std()), 6),
                "median": round(float(np.median(arr)), 6),
                "min": round(float(arr.min()), 6),
                "max": round(float(arr.max()), 6),
            },
            "feature_diff_sample_count": feature_diff_bars,
            "feature_diff_samples": feature_samples,
        }


def extract_backtest_metrics(result: dict[str, Any]) -> dict[str, Any]:
    hc = result.get("hold_chain") or {}
    stages = hc.get("ml_hold_stages") or {}
    metrics = result.get("metrics") or {}
    summary = result.get("summary") or {}
    bars = hc.get("bars_evaluated", 0) or 1
    buy_em = hc.get("buy_emitted", 0)
    sell_em = hc.get("sell_emitted", 0)
    return {
        "BUY": buy_em,
        "SELL": sell_em,
        "HOLD_decision": stages.get("decision_hold", 0),
        "signal_density_pct": round((buy_em + sell_em) / bars * 100, 4),
        "decision_hold": stages.get("decision_hold", 0),
        "engine_hold": None,
        "trade_count": result.get("trades", 0),
        "profit_factor": metrics.get("profit_factor"),
        "expectancy": metrics.get("expectancy"),
        "buy_pct_trades": summary.get("buy_pct"),
        "sell_pct_trades": summary.get("sell_pct"),
        "hold_pct": summary.get("hold_pct"),
        "elapsed_sec": result.get("elapsed_sec"),
    }
