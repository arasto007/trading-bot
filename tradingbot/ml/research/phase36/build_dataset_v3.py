"""Phase 36 — aligned dataset v3 builder (research only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.phase35.label_alignment import production_sl_tp_at_bar, resolve_label_with_sl_tp

META_COLS = {
    "timestamp", "symbol", "timeframe", "event_type", "event_time", "event_id",
    "timeframe_role", "entry_price", "direction", "stop_loss", "take_profit",
    "label", "future_window_bars", "tp_hit", "sl_hit", "mfe", "mae",
    "future_return", "risk_unit", "split", "dataset_schema_version",
}


def bar_index_for_timestamp(candles: pd.DataFrame, ts: pd.Timestamp) -> int:
    if ts in candles.index:
        loc = candles.index.get_loc(ts)
        return int(loc) if isinstance(loc, (int,)) else int(loc[0])
    return int(candles.index.searchsorted(ts, side="right") - 1)


def build_aligned_rows(
    df: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    confidence: float = 0.55,
    future_window: int = 72,
) -> pd.DataFrame:
    """Rebuild labels with production SL/TP for rows with candle coverage."""
    candle_min, candle_max = candles.index.min(), candles.index.max()
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work[(work["timestamp"] >= candle_min) & (work["timestamp"] <= candle_max)]
    work = work.sort_values("timestamp").reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        ts = row["timestamp"]
        idx = bar_index_for_timestamp(candles, ts)
        if idx < 20 or idx >= len(candles) - future_window - 1:
            continue
        direction = int(row["direction"])
        if direction not in (1, -1):
            continue
        entry = float(row["entry_price"])
        sl, tp = production_sl_tp_at_bar(candles, idx, direction, confidence=confidence)
        if sl <= 0 or tp <= 0:
            continue
        resolved = resolve_label_with_sl_tp(
            candles, idx, direction, sl, tp,
            future_window_bars=int(row.get("future_window_bars", future_window)),
            entry_price=entry,
        )
        label_v3 = int(resolved["label"])
        if label_v3 == int(Label.NO_RESOLUTION):
            continue

        out = row.to_dict()
        out["label_v2"] = int(row["label"])
        out["label_v3"] = label_v3
        out["stop_loss_v3"] = round(sl, 6)
        out["take_profit_v3"] = round(tp, 6)
        out["label_changed"] = int(row["label"]) != label_v3
        out["bar_index"] = idx
        rows.append(out)

    return pd.DataFrame(rows)


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in META_COLS and not c.startswith("label_") and c not in (
        "label_v2", "label_v3", "stop_loss_v3", "take_profit_v3", "label_changed", "bar_index",
    ) and df[c].dtype in ("float64", "float32", "int64", "int32")]
