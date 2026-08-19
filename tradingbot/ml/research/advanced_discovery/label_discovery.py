"""Phase 9.5 — advanced label configuration discovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import advanced_label_research_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.labels import compute_atr_at, compute_sl_tp
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.label_experiment import (
    SL_R,
    _atr_array,
    _precompute_events,
    _resolve_label_fast,
)

ATR_GRID: tuple[int, ...] = (14, 20, 50)
TP_GRID: tuple[float, ...] = (1.5, 2.0, 3.0)
WINDOW_GRID: tuple[int, ...] = (36, 72, 120, 180)

EVENT_FILTERS: dict[str, tuple[str, ...] | None] = {
    "all_events": None,
    "order_block_only": ("order_block",),
    "liquidity_sweep_only": ("liquidity_sweep",),
    "choch_only": ("choch",),
    "combined_smc": ("order_block", "choch", "fvg", "liquidity_sweep"),
}


def _simulate_precomputed(
    events: list[Any],
    candles: pd.DataFrame,
    atr_cache: dict[int, np.ndarray],
    *,
    atr_period: int,
    tp_r: float,
    window: int,
) -> dict[str, int]:
    highs = candles["high"].astype(float).values
    lows = candles["low"].astype(float).values
    atr_series = atr_cache[atr_period]
    tp = sl = nr = 0
    for ev in events:
        if ev is None:
            nr += 1
            continue
        risk = float(atr_series[ev.entry_idx])
        if risk <= 0 or not np.isfinite(risk):
            risk = compute_atr_at(candles, ev.entry_idx, atr_period)
        sl_p, tp_p = compute_sl_tp(ev.entry_price, ev.direction, risk, tp_r=tp_r, sl_r=SL_R)
        start = ev.entry_idx + 1
        label = _resolve_label_fast(
            highs[start:],
            lows[start:],
            sl=sl_p,
            tp=tp_p,
            direction=ev.direction,
            window=window,
        )
        if label == int(Label.TP_FIRST):
            tp += 1
        elif label == int(Label.SL_FIRST):
            sl += 1
        else:
            nr += 1
    return {"tp": tp, "sl": sl, "nr": nr, "total": len(events)}


def run_label_discovery(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Grid search label configurations without modifying dataset_v2."""
    candles = CandleStore(base_dir).load(symbol, timeframe)
    experiments: list[dict[str, Any]] = []

    if candles is None or candles.empty:
        return {
            "phase": "9.5",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "experiments": [],
            "notes": ["no candle data"],
        }

    atr_cache = {period: _atr_array(candles, period) for period in ATR_GRID}

    for filter_name, event_types in EVENT_FILTERS.items():
        work = df if event_types is None else df.loc[df["event_type"].isin(event_types)]
        if work.empty:
            continue
        events = _precompute_events(work, candles)
        for atr_period in ATR_GRID:
            for tp_r in TP_GRID:
                for window in WINDOW_GRID:
                    counts = _simulate_precomputed(
                        events,
                        candles,
                        atr_cache,
                        atr_period=atr_period,
                        tp_r=tp_r,
                        window=window,
                    )
                    total = counts["total"]
                    if total < 20:
                        continue
                    resolved = counts["tp"] + counts["sl"]
                    win_rate = counts["tp"] / resolved if resolved else 0.0
                    expectancy = win_rate * tp_r - (1.0 - win_rate) * SL_R if resolved else 0.0
                    experiments.append(
                        {
                            "filter_name": filter_name,
                            "event_filter": list(event_types) if event_types else None,
                            "atr_period": atr_period,
                            "tp_r_multiple": tp_r,
                            "future_window_bars": window,
                            "sample_count": total,
                            "resolved_count": resolved,
                            "tp_count": counts["tp"],
                            "sl_count": counts["sl"],
                            "unresolved_count": counts["nr"],
                            "label_balance_tp_rate": round(counts["tp"] / resolved, 4) if resolved else 0.0,
                            "win_rate": round(win_rate, 4),
                            "expectancy": round(expectancy, 4),
                        }
                    )

    best = _select_best_label(experiments)
    return {
        "phase": "9.5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "experiment_count": len(experiments),
        "experiments": experiments,
        "best_configuration": best,
    }


def _select_best_label(experiments: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not experiments:
        return None
    scored: list[tuple[float, dict[str, Any]]] = []
    for exp in experiments:
        balance_penalty = abs(exp.get("label_balance_tp_rate", 0.5) - 0.5)
        score = exp.get("expectancy", 0.0) - balance_penalty * 0.5 + exp.get("win_rate", 0.0) * 0.1
        scored.append((score, exp))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def save_advanced_label_research(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    report = run_label_discovery(df, symbol, timeframe, base_dir)
    path = advanced_label_research_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
