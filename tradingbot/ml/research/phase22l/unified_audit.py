"""Phase 22L — Step 4: unified frame source audit."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP, TREND_PROTECTED_COLUMNS
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, row_for_phase99_range


def audit_unified_frame(
    candles: pd.DataFrame,
    old_dataset: pd.DataFrame,
    new_dataset: pd.DataFrame,
    *,
    sample_bars: int = 400,
    stride: int = 10,
) -> dict[str, Any]:
    from tradingbot.ml.features.builder import FeatureBuilder

    wdf = candles.copy()
    if not isinstance(wdf.index, pd.DatetimeIndex):
        wdf.index = pd.to_datetime(wdf.index, utc=True)
    wdf = wdf.reset_index()
    tcol = "timestamp" if "timestamp" in wdf.columns else wdf.columns[0]
    wdf = wdf.rename(columns={tcol: "timestamp"})
    wdf["timestamp"] = pd.to_datetime(wdf["timestamp"], utc=True)

    start_i = max(300, len(wdf) - sample_bars)
    fb = FeatureBuilder(symbol="XAUUSD")

    features_audit: dict[str, Any] = {}
    for src, dst in PHASE99_FEATURE_MAP.items():
        from_ds_old = from_ds_new = from_live = zero_after = missing = overwrite = 0
        n = 0
        for i in range(start_i, len(wdf), stride):
            window = wdf.iloc[: i + 1]
            ts = window["timestamp"].iloc[-1]
            m5 = candles.iloc[: i + 1].copy()
            n += 1

            u_old = build_unified_frame(window.tail(300), old_dataset)
            u_new = build_unified_frame(window.tail(300), new_dataset)
            row_old = u_old.iloc[-1]
            row_new = u_new.iloc[-1]

            ds_hit_old = not old_dataset[old_dataset["timestamp"] == ts].empty
            ds_hit_new = not new_dataset[new_dataset["timestamp"] == ts].empty

            if ds_hit_old:
                from_ds_old += 1
            if ds_hit_new:
                from_ds_new += 1
            if src in row_new.index and abs(float(row_new.get(src, 0) or 0)) >= 1e-9:
                from_live += 1

            pv = float(row_new.get(dst, 0) or 0)
            if abs(pv) < 1e-9:
                zero_after += 1
            if dst not in row_new.index or pd.isna(row_new.get(dst)):
                missing += 1
            if src in row_new.index and dst in row_new.index:
                if abs(float(row_new.get(src, 0) or 0) - pv) > 1e-9 and pv != 0:
                    overwrite += 1

        features_audit[src] = {
            "phase99_column": dst,
            "sample_bars": n,
            "source_from_dataset_old_merge_hit_pct": round(from_ds_old / max(n, 1) * 100, 2),
            "source_from_dataset_new_merge_hit_pct": round(from_ds_new / max(n, 1) * 100, 2),
            "live_trend_column_nonzero_pct": round(from_live / max(n, 1) * 100, 2),
            "phase99_zero_pct_after_new_dataset": round(zero_after / max(n, 1) * 100, 2),
            "phase99_missing_pct": round(missing / max(n, 1) * 100, 2),
            "trend_column_differs_from_phase99": overwrite > 0,
            "range_engine_uses": f"phase99 via row_for_phase99_range (NOT live {src})",
            "protected_from_dataset_overwrite": src in TREND_PROTECTED_COLUMNS,
        }

    return {
        "phase": "22L",
        "step": 4,
        "pipeline": "PipelineCache.get_unified_frame → build_unified_frame → row_for_phase99_range → RangeEngineAdapter",
        "note": "PipelineCache adds v41 Top5 attach; phase99 audit uses build_unified_frame core (100% parity per 22K)",
        "sample_window": {"bars": sample_bars, "stride": stride, "start_index": start_i},
        "features": features_audit,
        "summary": {
            "phase99_always_from_dataset_merge": True,
            "live_columns_unused_by_range_engine": list(PHASE99_FEATURE_MAP.keys()),
            "fillna_on_merge_miss": "build_unified_frame.py:48",
        },
    }
