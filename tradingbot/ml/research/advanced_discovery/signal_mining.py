"""Phase 9.5 — event setup and signal mining."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import signal_mining_report_path
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.training.evaluation import label_r_outcomes, profit_factor

EVENT_TYPES: tuple[str, ...] = (
    "order_block",
    "choch",
    "fvg",
    "liquidity_sweep",
    "bos",
    "session_transition",
)

TP_R = 2.0
SL_R = 1.0


def _session_column(df: pd.DataFrame) -> pd.Series:
    if "in_london_kill" in df.columns:
        london = df["in_london_kill"].astype(float) > 0.5
        ny = df.get("in_ny_kill", pd.Series(0, index=df.index)).astype(float) > 0.5
        asia = df.get("session_asia", pd.Series(0, index=df.index)).astype(float) > 0.5
        return pd.Series(
            np.where(london, "london", np.where(ny, "new_york", np.where(asia, "asia", "other"))),
            index=df.index,
        )
    return pd.Series("unknown", index=df.index)


def _regime_column(df: pd.DataFrame) -> pd.Series:
    if "volatility_regime" not in df.columns:
        return pd.Series("unknown", index=df.index)
    reg = df["volatility_regime"].astype(float)
    return pd.Series(
        np.where(reg < 0.34, "low", np.where(reg > 0.66, "high", "mid")),
        index=df.index,
    )


def _event_metrics(subset: pd.DataFrame) -> dict[str, Any]:
    if subset.empty:
        return {"sample_count": 0}
    y = subset["label"].astype(int)
    tp = int((y == int(Label.TP_FIRST)).sum())
    sl = int((y == int(Label.SL_FIRST)).sum())
    resolved = tp + sl
    outcomes = label_r_outcomes(y.to_numpy())
    win_rate = round(tp / resolved, 4) if resolved else 0.0
    avg_r = round(float(outcomes.mean()), 4) if len(outcomes) else 0.0
    expectancy = avg_r
    pf = round(profit_factor(outcomes), 4) if len(outcomes) else 0.0

    sessions = _session_column(subset)
    regimes = _regime_column(subset)
    best_session = "unknown"
    best_session_wr = 0.0
    for sess in sessions.unique():
        part = subset.loc[sessions == sess]
        if len(part) < 3:
            continue
        wr = float((part["label"] == int(Label.TP_FIRST)).mean())
        if wr > best_session_wr:
            best_session_wr = wr
            best_session = str(sess)

    best_regime = "unknown"
    best_regime_wr = 0.0
    for reg in regimes.unique():
        part = subset.loc[regimes == reg]
        if len(part) < 3:
            continue
        wr = float((part["label"] == int(Label.TP_FIRST)).mean())
        if wr > best_regime_wr:
            best_regime_wr = wr
            best_regime = str(reg)

    return {
        "sample_count": len(subset),
        "tp_count": tp,
        "sl_count": sl,
        "win_rate": win_rate,
        "average_R": avg_r,
        "expectancy": expectancy,
        "profit_factor_proxy": pf,
        "best_session": best_session,
        "best_session_win_rate": round(best_session_wr, 4),
        "best_volatility_regime": best_regime,
        "best_regime_win_rate": round(best_regime_wr, 4),
    }


def run_signal_mining(df: pd.DataFrame) -> dict[str, Any]:
    """Mine profitability statistics per SMC event setup."""
    by_event: list[dict[str, Any]] = []
    for event in EVENT_TYPES:
        subset = df.loc[df["event_type"] == event]
        metrics = _event_metrics(subset)
        metrics["event_type"] = event
        if metrics.get("sample_count", 0) > 0:
            by_event.append(metrics)

    ranked = sorted(by_event, key=lambda e: (-e.get("expectancy", 0), -e.get("win_rate", 0)))
    best = ranked[0] if ranked else {}
    worst = ranked[-1] if ranked else {}

    return {
        "phase": "9.5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "events_analyzed": list(EVENT_TYPES),
        "by_event_type": by_event,
        "best_event": best.get("event_type"),
        "worst_event": worst.get("event_type"),
        "ranked_by_expectancy": [e.get("event_type") for e in ranked],
    }


def save_signal_mining_report(df: pd.DataFrame, base_dir: str | Path | None = None) -> Path:
    report = run_signal_mining(df)
    path = signal_mining_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
