"""Phase 22L — Step 3: feature coverage before/after refresh on Dataset A."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame


def _col_stats(series: pd.Series) -> dict[str, Any]:
    s = series.astype(float)
    n = max(len(s), 1)
    return {
        "zero_pct": round(float((s.fillna(0).abs() < 1e-9).mean()) * 100, 2),
        "missing_pct": round(float(s.isna().mean()) * 100, 2),
        "unique": int(s.nunique()),
        "variance": round(float(s.var()), 8) if len(s) > 1 else 0.0,
        "mean": round(float(s.mean()), 6),
        "std": round(float(s.std()), 6),
    }


def _merge_audit(candles: pd.DataFrame, dataset: pd.DataFrame, *, warmup: int = 300, stride: int = 5) -> dict[str, Any]:
    if candles is None or candles.empty:
        return {"error": "no_candles"}

    wdf = candles.copy()
    if not isinstance(wdf.index, pd.DatetimeIndex):
        wdf.index = pd.to_datetime(wdf.index, utc=True)
    wdf = wdf.reset_index()
    tcol = "timestamp" if "timestamp" in wdf.columns else wdf.columns[0]
    wdf = wdf.rename(columns={tcol: "timestamp"})
    wdf["timestamp"] = pd.to_datetime(wdf["timestamp"], utc=True)

    ds = dataset.copy()
    ds["timestamp"] = pd.to_datetime(ds["timestamp"], utc=True)
    ds_ts = set(ds["timestamp"])

    merge_hits = 0
    n = 0
    phase99_cols = list(PHASE99_FEATURE_MAP.values())
    unified_cols: Counter[str] = Counter()

    for i in range(warmup, len(wdf), max(1, stride)):
        window = wdf.iloc[: i + 1]
        ts = window["timestamp"].iloc[-1]
        n += 1
        if ts in ds_ts:
            merge_hits += 1
        unified = build_unified_frame(window.tail(300), ds)
        row = unified.iloc[-1]
        for col in phase99_cols:
            if col in row.index and abs(float(row.get(col, 0) or 0)) < 1e-9:
                unified_cols[col] += 1

    feature_coverage: dict[str, Any] = {}
    full_unified = build_unified_frame(wdf.tail(min(len(wdf), 5000)), ds)
    for col in phase99_cols:
        if col in full_unified.columns:
            feature_coverage[col] = _col_stats(full_unified[col])

    all_feat_cols = [c for c in full_unified.columns if c.startswith("phase99_")]
    for col in all_feat_cols:
        if col not in feature_coverage:
            feature_coverage[col] = _col_stats(full_unified[col])

    return {
        "bars_sampled": n,
        "merge_hit_count": merge_hits,
        "merge_hit_pct": round(merge_hits / max(n, 1) * 100, 2),
        "phase99_zero_on_sample": {k: {"count": v, "pct": round(v / max(n, 1) * 100, 2)} for k, v in unified_cols.items()},
        "unified_frame_feature_stats": feature_coverage,
        "dataset_max_ts": str(ds["timestamp"].max()),
        "candle_max_ts": str(wdf["timestamp"].max()),
    }


async def audit_feature_coverage(*, old_dataset: pd.DataFrame, new_dataset: pd.DataFrame) -> dict[str, Any]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from tradingbot.ml.research.phase22f.config import RapidDataset, build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset

    configure_research_env()
    dataset_a = build_dataset("A")
    candles = await load_ohlcv_for_dataset(dataset_a, "M5")
    if candles is None or candles.empty:
        return {"phase": "22L", "step": 3, "error": "no_dataset_a_candles"}

    before = _merge_audit(candles, old_dataset)
    after = _merge_audit(candles, new_dataset)

    return {
        "phase": "22L",
        "step": 3,
        "dataset_a": dataset_a.to_dict(),
        "before_refresh": before,
        "after_refresh": after,
        "merge_hit_delta_pct": round(after.get("merge_hit_pct", 0) - before.get("merge_hit_pct", 0), 2),
        "phase99_structure_distance_zero_delta": round(
            after.get("phase99_zero_on_sample", {}).get("phase99_structure_distance", {}).get("pct", 0)
            - before.get("phase99_zero_on_sample", {}).get("phase99_structure_distance", {}).get("pct", 0),
            2,
        ),
    }
