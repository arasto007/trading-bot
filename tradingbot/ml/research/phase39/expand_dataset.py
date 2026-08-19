"""Phase 39 — fast aligned dataset expansion on fullest candle history."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.phase36.build_dataset_v3 import META_COLS, feature_columns
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp

SL_TP_LOOKBACK = 80


def production_sl_tp_at_bar_fast(
    candles: pd.DataFrame,
    entry_index: int,
    direction: int,
    *,
    confidence: float = 0.55,
    symbol: str = "XAUUSD",
    lookback: int = SL_TP_LOOKBACK,
) -> tuple[float, float]:
    """Production compute_sl_tp using a bounded lookback window (parity verified)."""
    from tradingbot.domain.signal_helpers import compute_sl_tp

    start = max(0, entry_index - lookback + 1)
    window = candles.iloc[start : entry_index + 1]
    signal_int = 1 if direction > 0 else -1
    sl, tp, _ = compute_sl_tp(
        window,
        signal_int,
        confidence,
        symbol=symbol,
        strategy_name="ml_kernel_15b",
        timeframe="M5",
    )
    if sl is None or tp is None:
        return 0.0, 0.0
    return float(sl), float(tp)


def vectorized_bar_indices(candles: pd.DataFrame, timestamps: pd.Series) -> np.ndarray:
    cidx = pd.to_datetime(candles.index, utc=True).astype(np.int64)
    ts = pd.to_datetime(timestamps, utc=True).astype(np.int64)
    idx = np.searchsorted(cidx.to_numpy(), ts.to_numpy(), side="right") - 1
    return idx.astype(np.int64)


def build_aligned_rows_expanded(
    df: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    confidence: float = 0.55,
    future_window: int = 72,
) -> pd.DataFrame:
    """Rebuild v3 labels on fullest candle overlap with vectorized pre-filter."""
    candle_min, candle_max = candles.index.min(), candles.index.max()
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work[(work["timestamp"] >= candle_min) & (work["timestamp"] <= candle_max)]
    work = work.sort_values("timestamp").reset_index(drop=True)
    if work.empty:
        return pd.DataFrame()

    bar_idx = vectorized_bar_indices(candles, work["timestamp"])
    fw = work["future_window_bars"].fillna(future_window).astype(int).values
    valid = (
        (bar_idx >= 20)
        & (bar_idx < len(candles) - fw - 1)
        & work["direction"].isin([1, -1])
    )
    work = work.loc[valid].copy()
    bar_idx = bar_idx[valid]
    work["bar_index"] = bar_idx

    rows: list[dict[str, Any]] = []
    for i, row in work.iterrows():
        idx = int(row["bar_index"])
        direction = int(row["direction"])
        entry = float(row["entry_price"])
        sl, tp = production_sl_tp_at_bar_fast(candles, idx, direction, confidence=confidence)
        if sl <= 0 or tp <= 0:
            continue
        resolved = resolve_label_with_sl_tp(
            candles,
            idx,
            direction,
            sl,
            tp,
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
        rows.append(out)

    return pd.DataFrame(rows)


__all__ = [
    "SL_TP_LOOKBACK",
    "build_aligned_rows_expanded",
    "feature_columns",
    "production_sl_tp_at_bar_fast",
    "vectorized_bar_indices",
]
