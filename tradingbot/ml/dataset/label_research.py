"""Phase 8.2 label parameter research — simulation only, no dataset mutation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import label_research_report_path, reports_dir
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.labels import label_from_future_candles
from tradingbot.ml.dataset.schema import DatasetBuildConfig, Label

DEFAULT_WINDOWS: tuple[int, ...] = (36, 72, 120)
DEFAULT_ATR_PERIODS: tuple[int, ...] = (14, 20, 50)


@dataclass
class LabelConfigSimulation:
    future_window_bars: int
    atr_period: int
    total_samples: int
    resolved_samples: int
    tp_count: int
    sl_count: int
    no_resolution_count: int
    win_rate: float
    resolution_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LabelResearchReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    baseline: dict[str, Any] = field(default_factory=dict)
    simulations: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _entry_index(candles: pd.DataFrame, ts: pd.Timestamp) -> int | None:
    if candles is None or candles.empty:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    idx = candles.index
    if not isinstance(idx, pd.DatetimeIndex):
        return None
    pos = idx.searchsorted(ts, side="right") - 1
    if pos < 0 or pos >= len(candles):
        return None
    return int(pos)


def _simulate_config(
    df: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    future_window_bars: int,
    atr_period: int,
    tp_r: float,
    sl_r: float,
) -> LabelConfigSimulation:
    tp = sl = nr = 0
    resolved = 0

    for _, row in df.iterrows():
        ts = pd.Timestamp(row.get("event_time") or row.get("timestamp"))
        entry_idx = _entry_index(candles, ts)
        if entry_idx is None:
            nr += 1
            continue

        direction = int(row.get("direction", 0))
        entry_price = float(row.get("entry_price", 0.0)) or None
        result = label_from_future_candles(
            candles,
            entry_idx,
            direction,
            future_window_bars=future_window_bars,
            atr_period=atr_period,
            tp_r=tp_r,
            sl_r=sl_r,
            entry_price=entry_price,
        )
        if result.label == int(Label.TP_FIRST):
            tp += 1
            resolved += 1
        elif result.label == int(Label.SL_FIRST):
            sl += 1
            resolved += 1
        else:
            nr += 1

    total = len(df)
    win_rate = round(tp / resolved, 4) if resolved > 0 else 0.0
    resolution_rate = round(resolved / total, 4) if total > 0 else 0.0

    return LabelConfigSimulation(
        future_window_bars=future_window_bars,
        atr_period=atr_period,
        total_samples=total,
        resolved_samples=resolved,
        tp_count=tp,
        sl_count=sl,
        no_resolution_count=nr,
        win_rate=win_rate,
        resolution_rate=resolution_rate,
    )


def _baseline_from_dataset(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty or "label" not in df.columns:
        return {}
    tp = int((df["label"] == int(Label.TP_FIRST)).sum())
    sl = int((df["label"] == int(Label.SL_FIRST)).sum())
    nr = int((df["label"] == int(Label.NO_RESOLUTION)).sum())
    resolved = tp + sl
    window = int(df["future_window_bars"].iloc[0]) if "future_window_bars" in df.columns else 72
    return {
        "future_window_bars": window,
        "tp_count": tp,
        "sl_count": sl,
        "no_resolution_count": nr,
        "win_rate": round(tp / resolved, 4) if resolved > 0 else 0.0,
        "resolution_rate": round(resolved / len(df), 4),
    }


def run_label_research(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    base_dir: str | Path | None = None,
    config: DatasetBuildConfig | None = None,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    atr_periods: tuple[int, ...] = DEFAULT_ATR_PERIODS,
) -> LabelResearchReport:
    """
    Simulate alternative label configurations without modifying the stored dataset.
    """
    cfg = config or DatasetBuildConfig(symbol=symbol, timeframe=timeframe)
    now = datetime.now(timezone.utc).isoformat()
    report = LabelResearchReport(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=now,
        baseline=_baseline_from_dataset(df),
    )

    if df is None or df.empty:
        report.notes.append("empty dataset")
        return report

    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        report.notes.append("no candle data available for simulation — baseline only")
        return report

    simulations: list[dict[str, Any]] = []
    for window in windows:
        for atr_period in atr_periods:
            sim = _simulate_config(
                df,
                candles,
                future_window_bars=window,
                atr_period=atr_period,
                tp_r=cfg.tp_r_multiple,
                sl_r=cfg.sl_r_multiple,
            )
            simulations.append(sim.to_dict())

    report.simulations = simulations
    return report


def save_label_research_report(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
    config: DatasetBuildConfig | None = None,
) -> Path:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    report = run_label_research(df, symbol, timeframe, base_dir=base_dir, config=config)
    path = label_research_report_path(symbol, timeframe, base_dir)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
