"""Phase 15K — engine replay trace on TREND bars."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase15k.config import TREND_THRESHOLD
from tradingbot.ml.research.phase15k.data_access import iter_trend_bars, load_frozen_bundle


def _leaf_path_summary(model, scaled_row: np.ndarray) -> dict[str, Any]:
    tree_leaves = tuple(int(x) for x in np.asarray(model.apply(scaled_row)).ravel())
    return {
        "leaf_id": tree_leaves[0] if tree_leaves else -1,
        "path_length": len(tree_leaves),
        "tree_leaf_ids": list(tree_leaves[:10]),
    }


def replay_engine_trace(
    candles,
    dataset,
    *,
    base_dir: str | None = None,
    days: int = 365,
    stride: int = 15,
    max_records: int = 500,
    **_: Any,
) -> dict[str, Any]:
    bundle = load_frozen_bundle(base_dir=base_dir)
    model = bundle.model
    threshold = float(bundle.config.get("threshold", TREND_THRESHOLD))

    records: list[dict[str, Any]] = []
    first_cap_bar: dict[str, Any] | None = None
    global_max = 0.0

    for _i, row, ts in iter_trend_bars(candles, dataset, days=days, stride=stride):
        feats = {f: float(row.get(f, 0.0)) for f in bundle.feature_order}
        feat_vec = np.array([[feats[f] for f in bundle.feature_order]], dtype=float)
        scaled = bundle.scaler.transform(feat_vec)
        prob = float(bundle.predict_proba(feats))
        global_max = max(global_max, prob)
        path_info = _leaf_path_summary(model, scaled)
        below_threshold = prob < threshold
        cap_reason = (
            f"probability {prob:.4f} < threshold {threshold}"
            if below_threshold
            else "passes_threshold"
        )
        rec = {
            "timestamp": str(ts),
            "input_features": feats,
            "rf_probability": round(prob, 6),
            "leaf_path": path_info,
            "final_probability": round(prob, 6),
            "below_threshold": below_threshold,
            "cap_reason": cap_reason,
        }
        records.append(rec)
        if first_cap_bar is None and below_threshold:
            first_cap_bar = rec
        if len(records) >= max_records:
            break

    return {
        "phase": "15K",
        "threshold": threshold,
        "bars_replayed": len(records),
        "global_max_probability": round(global_max, 6),
        "first_cap_occurrence": first_cap_bar,
        "all_below_threshold": global_max < threshold,
        "records": records[:100],
        "records_truncated": max(0, len(records) - 100),
    }
