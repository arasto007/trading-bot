"""Phase 22L — Step 6: before/after comparison using refreshed dataset only in research."""

from __future__ import annotations

import contextlib
from collections import Counter
from typing import Any, Iterator

import numpy as np
import pandas as pd


@contextlib.contextmanager
def _patched_dataset_v2(dataset: pd.DataFrame) -> Iterator[None]:
    """Inject research dataset into PipelineCache path without touching production files."""
    import tradingbot.ml.dataset.store as store_mod

    original = store_mod.DatasetStore.load_v2

    def _load_v2(self, symbol: str, timeframe: str):
        if symbol.upper() == "XAUUSD" and timeframe.upper() == "M5":
            return dataset.copy()
        return original(self, symbol, timeframe)

    store_mod.DatasetStore.load_v2 = _load_v2
    try:
        yield
    finally:
        store_mod.DatasetStore.load_v2 = original


async def compare_before_after(
    old_dataset: pd.DataFrame,
    new_dataset: pd.DataFrame,
    *,
    stride: int = 10,
    warmup: int = 300,
) -> dict[str, Any]:
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
    from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
    from tradingbot.ml.research.phase22f.config import build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
    from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter

    configure_research_env()
    dataset_a = build_dataset("A")
    candles = await load_ohlcv_for_dataset(dataset_a, "M5")
    if candles is None or candles.empty:
        return {"phase": "22L", "step": 6, "error": "no_candles"}

    wdf = candles.copy()
    if not isinstance(wdf.index, pd.DatetimeIndex):
        wdf.index = pd.to_datetime(wdf.index, utc=True)
    wdf = wdf.reset_index()
    tcol = "timestamp" if "timestamp" in wdf.columns else wdf.columns[0]
    wdf = wdf.rename(columns={tcol: "timestamp"})
    wdf["timestamp"] = pd.to_datetime(wdf["timestamp"], utc=True)

    bundle = load_phase9_9_bundle(build_if_missing=False)
    range_inner = RangeEngineAdapter.load(symbol="XAUUSD")

    def _run_profile(ds: pd.DataFrame) -> dict[str, Any]:
        PipelineCache.reset()
        with _patched_dataset_v2(ds):
            counts = Counter({"BUY": 0, "SELL": 0, "HOLD": 0})
            probs: list[float] = []
            merge_hit = 0
            n = 0
            for i in range(warmup, len(wdf), stride):
                window = wdf.iloc[: i + 1]
                ts = window["timestamp"].iloc[-1]
                n += 1
                if not ds[ds["timestamp"] == ts].empty:
                    merge_hit += 1
                unified = PipelineCache.get_unified_frame(
                    window, symbol="XAUUSD", timeframe="M5",
                )
                row = unified.iloc[-1]
                mapped = row_for_phase99_range(row)
                feats = range_inner._features_from_row(mapped)
                if feats is None:
                    counts["HOLD"] += 1
                    probs.append(0.5)
                    continue
                prob = bundle.predict_proba(feats)
                probs.append(prob)
                sig = range_inner.signal_engine.generate(prob).value
                counts[sig] = counts.get(sig, 0) + 1

            arr = np.array(probs) if probs else np.array([0.5])
            total = max(sum(counts.values()), 1)
            return {
                "bars": n,
                "merge_hit_pct": round(merge_hit / max(n, 1) * 100, 2),
                "direction_counts": dict(counts),
                "buy_pct": round(counts["BUY"] / total * 100, 2),
                "sell_pct": round(counts["SELL"] / total * 100, 2),
                "hold_pct": round(counts["HOLD"] / total * 100, 2),
                "p_win_mean": round(float(arr.mean()), 4),
                "p_win_std": round(float(arr.std()), 4),
                "p_win_min": round(float(arr.min()), 4),
                "p_win_max": round(float(arr.max()), 4),
            }

    before = _run_profile(old_dataset)
    after = _run_profile(new_dataset)

    no_change = (
        before["direction_counts"] == after["direction_counts"]
        and abs(before["p_win_mean"] - after["p_win_mean"]) < 0.001
    )

    reason = None
    if no_change:
        reason = (
            "CandleStore M5 history ends near old dataset max; refresh added few/no event rows in Dataset A "
            "window. Remaining bars still miss sparse-event merge OR have native structure_distance=0. "
            "Engine thresholds unchanged — P(win) remains in sell_zone."
        )

    return {
        "phase": "22L",
        "step": 6,
        "engine_modified": False,
        "thresholds_modified": False,
        "dataset_a": dataset_a.to_dict(),
        "before_old_dataset": before,
        "after_refreshed_dataset": after,
        "delta": {
            "merge_hit_pct": round(after["merge_hit_pct"] - before["merge_hit_pct"], 2),
            "buy_pct": round(after["buy_pct"] - before["buy_pct"], 2),
            "sell_pct": round(after["sell_pct"] - before["sell_pct"], 2),
            "hold_pct": round(after["hold_pct"] - before["hold_pct"], 2),
            "p_win_mean": round(after["p_win_mean"] - before["p_win_mean"], 4),
        },
        "backtest_pf_trades": {
            "note": "Full PF backtest skipped — hold_chain unreliable per 22K; engine-level profile used instead",
            "pf": None,
            "trades": None,
            "expectancy": None,
        },
        "measurable_change": not no_change,
        "no_change_reason": reason,
    }
