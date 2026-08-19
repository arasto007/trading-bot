"""Phase 35 — label alignment utilities (research only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.dataset.schema import Label


def resolve_label_with_sl_tp(
    candles: pd.DataFrame,
    entry_index: int,
    direction: int,
    stop_loss: float,
    take_profit: float,
    *,
    future_window_bars: int = 72,
    entry_price: float | None = None,
) -> dict[str, Any]:
    """Forward-resolve TP/SL hit using explicit levels (no look-ahead)."""
    if candles is None or candles.empty or entry_index < 0 or entry_index >= len(candles) - 1:
        return {"label": int(Label.NO_RESOLUTION), "tp_hit": False, "sl_hit": False, "exit_reason": "no_data"}

    entry = float(entry_price if entry_price is not None else candles["close"].iloc[entry_index])
    sl, tp = float(stop_loss), float(take_profit)
    start = entry_index + 1
    end = min(len(candles), entry_index + 1 + future_window_bars)

    for j in range(start, end):
        hi = float(candles.iloc[j]["high"])
        lo = float(candles.iloc[j]["low"])
        if direction > 0:
            bar_sl = lo <= sl
            bar_tp = hi >= tp
        else:
            bar_sl = hi >= sl
            bar_tp = lo <= tp
        if bar_sl and bar_tp:
            return {"label": int(Label.SL_FIRST), "tp_hit": False, "sl_hit": True, "exit_reason": "sl", "bars": j - entry_index}
        if bar_sl:
            return {"label": int(Label.SL_FIRST), "tp_hit": False, "sl_hit": True, "exit_reason": "sl", "bars": j - entry_index}
        if bar_tp:
            return {"label": int(Label.TP_FIRST), "tp_hit": True, "sl_hit": False, "exit_reason": "tp", "bars": j - entry_index}

    return {"label": int(Label.NO_RESOLUTION), "tp_hit": False, "sl_hit": False, "exit_reason": "timeout", "bars": end - entry_index}


def production_sl_tp_at_bar(
    candles: pd.DataFrame,
    entry_index: int,
    direction: int,
    *,
    confidence: float = 0.55,
    symbol: str = "XAUUSD",
) -> tuple[float, float]:
    """Production compute_sl_tp at bar (read-only call)."""
    from tradingbot.domain.signal_helpers import compute_sl_tp

    window = candles.iloc[: entry_index + 1]
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


def sl_tp_distance_metrics(
    entry: float,
    direction: int,
    sl_a: float,
    tp_a: float,
    sl_b: float,
    tp_b: float,
) -> dict[str, float]:
    """Compare SL/TP distances between dataset and production."""
    if entry <= 0:
        return {"sl_dist_delta_pct": 0.0, "tp_dist_delta_pct": 0.0, "rr_a": 0.0, "rr_b": 0.0}
    sl_dist_a = abs(entry - sl_a)
    tp_dist_a = abs(tp_a - entry)
    sl_dist_b = abs(entry - sl_b)
    tp_dist_b = abs(tp_b - entry)
    rr_a = tp_dist_a / sl_dist_a if sl_dist_a > 0 else 0.0
    rr_b = tp_dist_b / sl_dist_b if sl_dist_b > 0 else 0.0
    return {
        "sl_dist_delta_pct": round(abs(sl_dist_a - sl_dist_b) / max(sl_dist_a, 1e-9) * 100, 2),
        "tp_dist_delta_pct": round(abs(tp_dist_a - tp_dist_b) / max(tp_dist_a, 1e-9) * 100, 2),
        "rr_dataset": round(rr_a, 4),
        "rr_production": round(rr_b, 4),
        "rr_delta": round(abs(rr_a - rr_b), 4),
    }
