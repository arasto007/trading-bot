"""Event outcome labeling — TP/SL resolution using future candles only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import (
    DEFAULT_FUTURE_WINDOW_M5,
    DEFAULT_RR_SL,
    DEFAULT_RR_TP,
    Label,
)


@dataclass
class LabelResult:
    label: int
    tp_hit: bool
    sl_hit: bool
    mfe: float
    mae: float
    future_return: float
    stop_loss: float
    take_profit: float
    risk_unit: float
    entry_price: float
    direction: int
    future_window_bars: int
    resolution_bar: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": int(self.label),
            "tp_hit": self.tp_hit,
            "sl_hit": self.sl_hit,
            "mfe": self.mfe,
            "mae": self.mae,
            "future_return": self.future_return,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_unit": self.risk_unit,
            "entry_price": self.entry_price,
            "direction": self.direction,
            "future_window_bars": self.future_window_bars,
        }


def compute_atr_at(candles: pd.DataFrame, index: int, period: int = 14) -> float:
    """ATR at bar index using only candles up to and including index."""
    if candles is None or candles.empty or index < 0:
        return 0.0
    idx = min(index, len(candles) - 1)
    work = candles.iloc[: idx + 1]
    if len(work) < period + 1:
        return float(work["close"].iloc[-1]) * 0.001
    h, l, c = work["high"], work["low"], work["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=period).mean().iloc[-1]
    return float(atr) if not pd.isna(atr) else float(work["close"].iloc[-1]) * 0.001


def compute_sl_tp(
    entry_price: float,
    direction: int,
    risk_unit: float,
    *,
    tp_r: float = DEFAULT_RR_TP,
    sl_r: float = DEFAULT_RR_SL,
) -> tuple[float, float]:
    """SL = 1R, TP = 2R by default."""
    r = max(risk_unit, 1e-9)
    if direction > 0:
        return entry_price - sl_r * r, entry_price + tp_r * r
    if direction < 0:
        return entry_price + sl_r * r, entry_price - tp_r * r
    return entry_price, entry_price


def label_from_future_candles(
    candles: pd.DataFrame,
    entry_index: int,
    direction: int,
    *,
    future_window_bars: int = DEFAULT_FUTURE_WINDOW_M5,
    atr_period: int = 14,
    tp_r: float = DEFAULT_RR_TP,
    sl_r: float = DEFAULT_RR_SL,
    entry_price: float | None = None,
) -> LabelResult:
    """
    Label a decision point using only candles AFTER entry_index.

    label: 1 = TP before SL, 0 = SL before TP, -1 = no resolution in window.
    """
    if candles is None or candles.empty or entry_index < 0 or entry_index >= len(candles):
        return _empty_label(future_window_bars)

    entry = float(entry_price if entry_price is not None else candles["close"].iloc[entry_index])
    if direction == 0:
        direction = 1 if candles["close"].iloc[entry_index] >= candles["open"].iloc[entry_index] else -1

    risk_unit = compute_atr_at(candles, entry_index, atr_period)
    sl, tp = compute_sl_tp(entry, direction, risk_unit, tp_r=tp_r, sl_r=sl_r)

    start = entry_index + 1
    end = min(len(candles), entry_index + 1 + future_window_bars)
    future = candles.iloc[start:end]
    if future.empty:
        return LabelResult(
            label=int(Label.NO_RESOLUTION),
            tp_hit=False,
            sl_hit=False,
            mfe=0.0,
            mae=0.0,
            future_return=0.0,
            stop_loss=sl,
            take_profit=tp,
            risk_unit=risk_unit,
            entry_price=entry,
            direction=direction,
            future_window_bars=future_window_bars,
        )

    highs = future["high"].astype(float).values
    lows = future["low"].astype(float).values
    closes = future["close"].astype(float).values

    if direction > 0:
        mfe = float(np.max((highs - entry) / risk_unit)) if risk_unit > 0 else 0.0
        mae = float(np.max((entry - lows) / risk_unit)) if risk_unit > 0 else 0.0
    else:
        mfe = float(np.max((entry - lows) / risk_unit)) if risk_unit > 0 else 0.0
        mae = float(np.max((highs - entry) / risk_unit)) if risk_unit > 0 else 0.0

    tp_hit = False
    sl_hit = False
    label = int(Label.NO_RESOLUTION)
    resolution_bar = None

    for j in range(len(future)):
        hi, lo = highs[j], lows[j]
        if direction > 0:
            bar_sl = lo <= sl
            bar_tp = hi >= tp
        else:
            bar_sl = hi >= sl
            bar_tp = lo <= tp

        if bar_sl and bar_tp:
            # Conservative: SL checked before TP within same bar
            sl_hit = True
            label = int(Label.SL_FIRST)
            resolution_bar = start + j
            break
        if bar_sl:
            sl_hit = True
            label = int(Label.SL_FIRST)
            resolution_bar = start + j
            break
        if bar_tp:
            tp_hit = True
            label = int(Label.TP_FIRST)
            resolution_bar = start + j
            break

    last_close = float(closes[-1])
    future_return = ((last_close - entry) / entry) * direction if entry > 0 else 0.0

    return LabelResult(
        label=label,
        tp_hit=tp_hit,
        sl_hit=sl_hit,
        mfe=round(mfe, 6),
        mae=round(mae, 6),
        future_return=round(future_return, 6),
        stop_loss=round(sl, 6),
        take_profit=round(tp, 6),
        risk_unit=round(risk_unit, 6),
        entry_price=round(entry, 6),
        direction=direction,
        future_window_bars=future_window_bars,
        resolution_bar=resolution_bar,
    )


def _empty_label(future_window_bars: int) -> LabelResult:
    return LabelResult(
        label=int(Label.NO_RESOLUTION),
        tp_hit=False,
        sl_hit=False,
        mfe=0.0,
        mae=0.0,
        future_return=0.0,
        stop_loss=0.0,
        take_profit=0.0,
        risk_unit=0.0,
        entry_price=0.0,
        direction=0,
        future_window_bars=future_window_bars,
    )


def verify_rr_ratio(result: LabelResult, *, tp_r: float = DEFAULT_RR_TP, sl_r: float = DEFAULT_RR_SL) -> bool:
    """Verify TP distance = tp_r * R and SL distance = sl_r * R."""
    if result.direction == 0 or result.risk_unit <= 0:
        return True
    entry = result.entry_price
    tp_dist = abs(result.take_profit - entry)
    sl_dist = abs(result.stop_loss - entry)
    r = result.risk_unit
    return abs(tp_dist - tp_r * r) < 1e-6 and abs(sl_dist - sl_r * r) < 1e-6
