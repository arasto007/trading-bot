"""Phase 13.8 — trend label variants (v2)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.phase13_8.config import MAX_HOLD_BARS
from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels
from tradingbot.ml.research.trend_strategy.trend_signal import build_trend_signal


def _label_tp_before_sl(work: pd.DataFrame, i: int, *, direction: str, entry: float, sl: float, tp: float) -> int | None:
    exit_bar = min(i + MAX_HOLD_BARS, len(work) - 1)
    for j in range(i + 1, exit_bar + 1):
        bar = work.iloc[j]
        hi, lo = float(bar["high"]), float(bar["low"])
        if direction == "BUY":
            if lo <= sl:
                return 0
            if hi >= tp:
                return 1
        else:
            if hi >= sl:
                return 0
            if lo <= tp:
                return 1
    return None


def _label_mfe_2r(work: pd.DataFrame, i: int, *, direction: str, entry: float, sl: float) -> int | None:
    r_unit = abs(entry - sl)
    if r_unit <= 0:
        return None
    target = entry + 2 * r_unit if direction == "BUY" else entry - 2 * r_unit
    exit_bar = min(i + MAX_HOLD_BARS, len(work) - 1)
    hit_sl = False
    for j in range(i + 1, exit_bar + 1):
        bar = work.iloc[j]
        hi, lo = float(bar["high"]), float(bar["low"])
        if direction == "BUY":
            if lo <= sl:
                hit_sl = True
                break
            if hi >= target:
                return 1
        else:
            if hi >= sl:
                hit_sl = True
                break
            if lo <= target:
                return 1
    return 0 if hit_sl else None


def _label_continuation_1r(work: pd.DataFrame, i: int, *, direction: str, entry: float, sl: float, regimes: pd.Series) -> int | None:
    r_unit = abs(entry - sl)
    if r_unit <= 0:
        return None
    target = entry + r_unit if direction == "BUY" else entry - r_unit
    exit_bar = min(i + MAX_HOLD_BARS, len(work) - 1)
    reached_1r = False
    for j in range(i + 1, exit_bar + 1):
        bar = work.iloc[j]
        hi, lo = float(bar["high"]), float(bar["low"])
        if str(regimes.iloc[j]) != "TREND":
            return 1 if reached_1r else 0
        if direction == "BUY":
            if lo <= sl:
                return 0
            if hi >= target:
                reached_1r = True
        else:
            if hi >= sl:
                return 0
            if lo <= target:
                reached_1r = True
    return 1 if reached_1r else None


LABEL_FNS: dict[str, Callable[..., int | None]] = {
    "label_a_tp_before_sl": _label_tp_before_sl,
    "label_b_mfe_2r": lambda w, i, **kw: _label_mfe_2r(w, i, direction=kw["direction"], entry=kw["entry"], sl=kw["sl"]),
    "label_c_continuation_1r": _label_continuation_1r,
}


def build_labeled_samples(
    frame: pd.DataFrame,
    *,
    symbol: str,
    rule_fn: Callable[..., str],
    label_key: str = "label_a_tp_before_sl",
) -> pd.DataFrame:
    work = frame.copy().reset_index(drop=True)
    regimes = attach_regime_labels(work)
    label_fn = LABEL_FNS[label_key]
    rows: list[dict[str, Any]] = []

    for i in range(len(work) - 1):
        row = work.iloc[i]
        regime = str(regimes.iloc[i])
        direction = rule_fn(row, regime=regime)
        if direction == "HOLD":
            continue
        signal = build_trend_signal(row, symbol=symbol, direction=direction)
        entry = float(signal["entry"])
        sl = float(signal["stop_loss"])
        tp = float(signal["take_profit"])
        if label_key == "label_a_tp_before_sl":
            label = _label_tp_before_sl(work, i, direction=direction, entry=entry, sl=sl, tp=tp)
        elif label_key == "label_b_mfe_2r":
            label = _label_mfe_2r(work, i, direction=direction, entry=entry, sl=sl)
        elif label_key == "label_c_continuation_1r":
            label = _label_continuation_1r(work, i, direction=direction, entry=entry, sl=sl, regimes=regimes)
        else:
            label = None
        if label is None:
            continue
        rows.append(
            {
                "timestamp": row["timestamp"],
                "direction": direction,
                "regime": regime,
                "successful_trade": int(label),
                **{c: float(row[c]) for c in work.columns if c in row.index and c not in ("timestamp",)},
            }
        )
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def compare_labels(
    frame: pd.DataFrame,
    *,
    symbol: str,
    rule_fn: Callable[..., str],
) -> dict[str, Any]:
    results = []
    for key in LABEL_FNS:
        samples = build_labeled_samples(frame, symbol=symbol, rule_fn=rule_fn, label_key=key)
        pos_rate = float(samples["successful_trade"].mean()) if not samples.empty else 0.0
        results.append(
            {
                "label": key,
                "samples": len(samples),
                "positive_rate": round(pos_rate, 4),
            }
        )
    best = max(results, key=lambda r: r["samples"]) if results else {}
    return {"comparison": results, "best_label": best.get("label"), "labels": list(LABEL_FNS.keys())}
