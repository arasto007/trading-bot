"""Phase 9.3 — label configuration experiments (simulation only, no dataset mutation)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import label_experiments_report_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.label_research import _baseline_from_dataset
from tradingbot.ml.dataset.labels import compute_atr_at, compute_sl_tp
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.dataset.store import DatasetStore

ATR_PERIODS: tuple[int, ...] = (14, 20, 50)
TP_R_MULTIPLES: tuple[float, ...] = (2.0, 2.5, 3.0)
FUTURE_WINDOWS: tuple[int, ...] = (36, 72, 120)
SL_R = 1.0

RESEARCH_ATR_PERIOD = 20
RESEARCH_TP_R = 2.0
RESEARCH_FUTURE_WINDOW = 120


@dataclass(frozen=True)
class _EventRef:
    entry_idx: int
    direction: int
    entry_price: float


def _atr_array(candles: pd.DataFrame, period: int) -> np.ndarray:
    """Precompute ATR for all bars once (avoids repeated rolling per event)."""
    h = candles["high"].astype(float).values
    l = candles["low"].astype(float).values
    c = candles["close"].astype(float).values
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    out = np.full(len(tr), np.nan, dtype=float)
    if len(tr) < period:
        return out
    for i in range(period - 1, len(tr)):
        out[i] = tr[i - period + 1 : i + 1].mean()
    return out


def _precompute_events(df: pd.DataFrame, candles: pd.DataFrame) -> list[_EventRef | None]:
    """Vectorized event-time → bar index mapping."""
    idx = candles.index
    if not isinstance(idx, pd.DatetimeIndex):
        return [None] * len(df)

    event_times = pd.to_datetime(
        df["event_time"].where(df["event_time"].notna(), df["timestamp"]),
        utc=True,
    )
    positions = idx.searchsorted(event_times, side="right") - 1
    opens = candles["open"].astype(float).values
    closes = candles["close"].astype(float).values

    events: list[_EventRef | None] = []
    for i, pos in enumerate(positions):
        if pos < 0 or pos >= len(candles):
            events.append(None)
            continue
        direction = int(df["direction"].iloc[i])
        if direction == 0:
            direction = 1 if closes[pos] >= opens[pos] else -1
        entry_price = float(df["entry_price"].iloc[i])
        if not entry_price:
            entry_price = float(closes[pos])
        events.append(_EventRef(entry_idx=int(pos), direction=direction, entry_price=entry_price))
    return events


def _resolve_label_fast(
    highs: np.ndarray,
    lows: np.ndarray,
    *,
    sl: float,
    tp: float,
    direction: int,
    window: int,
) -> int:
    end = min(len(highs), window)
    for j in range(end):
        hi, lo = float(highs[j]), float(lows[j])
        if direction > 0:
            bar_sl, bar_tp = lo <= sl, hi >= tp
        else:
            bar_sl, bar_tp = hi >= sl, lo <= tp
        if bar_sl and bar_tp:
            return int(Label.SL_FIRST)
        if bar_sl:
            return int(Label.SL_FIRST)
        if bar_tp:
            return int(Label.TP_FIRST)
    return int(Label.NO_RESOLUTION)


def _simulate_fast(
    events: list[_EventRef | None],
    candles: pd.DataFrame,
    atr_cache: dict[int, np.ndarray],
    *,
    future_window_bars: int,
    atr_period: int,
    tp_r: float,
) -> dict[str, Any]:
    highs_all = candles["high"].astype(float).values
    lows_all = candles["low"].astype(float).values
    atr_series = atr_cache[atr_period]

    tp = sl = nr = 0
    for ev in events:
        if ev is None:
            nr += 1
            continue
        risk_unit = float(atr_series[ev.entry_idx])
        if not np.isfinite(risk_unit) or risk_unit <= 0:
            risk_unit = compute_atr_at(candles, ev.entry_idx, atr_period)
        sl_price, tp_price = compute_sl_tp(
            ev.entry_price,
            ev.direction,
            risk_unit,
            tp_r=tp_r,
            sl_r=SL_R,
        )
        start = ev.entry_idx + 1
        label = _resolve_label_fast(
            highs_all[start:],
            lows_all[start:],
            sl=sl_price,
            tp=tp_price,
            direction=ev.direction,
            window=future_window_bars,
        )
        if label == int(Label.TP_FIRST):
            tp += 1
        elif label == int(Label.SL_FIRST):
            sl += 1
        else:
            nr += 1

    total = len(events)
    resolved = tp + sl
    return {
        "future_window_bars": future_window_bars,
        "atr_period": atr_period,
        "tp_r_multiple": tp_r,
        "sl_r_multiple": SL_R,
        "total_samples": total,
        "resolved_samples": resolved,
        "tp_count": tp,
        "sl_count": sl,
        "no_resolution_count": nr,
        "tp_percentage": round(tp / total, 4) if total else 0.0,
        "sl_percentage": round(sl / total, 4) if total else 0.0,
        "unresolved_percentage": round(nr / total, 4) if total else 0.0,
        "class_balance_tp_rate": round(tp / resolved, 4) if resolved else 0.0,
        "class_balance_sl_rate": round(sl / resolved, 4) if resolved else 0.0,
        "resolution_rate": round(resolved / total, 4) if total else 0.0,
        "win_rate": round(tp / resolved, 4) if resolved else 0.0,
    }


def relabel_dataframe(
    df: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    atr_period: int = 20,
    tp_r: float = 2.0,
    future_window_bars: int = 120,
    sl_r: float = SL_R,
) -> pd.DataFrame:
    """Apply research label configuration to a copy — does not modify source frame."""
    out = df.copy()
    events = _precompute_events(df, candles)
    atr_series = _atr_array(candles, atr_period)
    highs_all = candles["high"].astype(float).values
    lows_all = candles["low"].astype(float).values
    labels: list[int] = []
    for ev in events:
        if ev is None:
            labels.append(int(Label.NO_RESOLUTION))
            continue
        risk_unit = float(atr_series[ev.entry_idx])
        if not np.isfinite(risk_unit) or risk_unit <= 0:
            risk_unit = compute_atr_at(candles, ev.entry_idx, atr_period)
        sl_price, tp_price = compute_sl_tp(
            ev.entry_price,
            ev.direction,
            risk_unit,
            tp_r=tp_r,
            sl_r=sl_r,
        )
        start = ev.entry_idx + 1
        labels.append(
            _resolve_label_fast(
                highs_all[start:],
                lows_all[start:],
                sl=sl_price,
                tp=tp_price,
                direction=ev.direction,
                window=future_window_bars,
            )
        )
    out["label"] = labels
    out["future_window_bars"] = future_window_bars
    return out


def run_label_experiments(
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Research alternative labeling configurations without modifying dataset_v2.

    Reads dataset_v2 for event metadata only; simulates labels from candles.
    """
    store = DatasetStore(base_dir)
    df = store.load_v2(symbol, timeframe)
    if df is None or df.empty:
        raise FileNotFoundError(f"Dataset v2 not found for {symbol} {timeframe}")

    original_labels = df["label"].copy() if "label" in df.columns else None

    report: dict[str, Any] = {
        "phase": "9.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "baseline": _baseline_from_dataset(df),
        "experiments": [],
        "notes": [],
    }

    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        report["notes"].append("no candle data — experiments skipped")
        return report

    events = _precompute_events(df, candles)
    atr_cache = {period: _atr_array(candles, period) for period in ATR_PERIODS}

    experiments: list[dict[str, Any]] = []
    for window in FUTURE_WINDOWS:
        for atr_period in ATR_PERIODS:
            for tp_r in TP_R_MULTIPLES:
                experiments.append(
                    _simulate_fast(
                        events,
                        candles,
                        atr_cache,
                        future_window_bars=window,
                        atr_period=atr_period,
                        tp_r=tp_r,
                    )
                )

    report["experiments"] = experiments

    if original_labels is not None:
        reloaded = store.load_v2(symbol, timeframe)
        assert reloaded is not None
        if not reloaded["label"].equals(original_labels):
            report["notes"].append("WARNING: dataset labels were mutated (unexpected)")

    return report


def select_best_label_configuration(experiments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick experiment closest to balanced TP/SL among resolved samples."""
    if not experiments:
        return None
    scored = []
    for exp in experiments:
        tp_rate = exp.get("class_balance_tp_rate", 0.0)
        balance_penalty = abs(tp_rate - 0.5)
        resolution = exp.get("resolution_rate", 0.0)
        scored.append((balance_penalty - resolution * 0.1, exp))
    scored.sort(key=lambda x: x[0])
    return scored[0][1]


def save_label_experiments_report(
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    report = run_label_experiments(symbol, timeframe, base_dir)
    path = label_experiments_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
