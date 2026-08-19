"""Dataset statistics generation for Phase 3.1 hardening."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import dataset_statistics_report_path, reports_dir
from tradingbot.ml.dataset.schema import Label


@dataclass
class DatasetStatistics:
    symbol: str
    timeframe: str
    generated_at_utc: str
    rows: int = 0
    labels: dict[str, int] = field(default_factory=dict)
    rows_per_event_type: dict[str, int] = field(default_factory=dict)
    rows_per_direction: dict[str, int] = field(default_factory=dict)
    split_distribution: dict[str, int] = field(default_factory=dict)
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    win_rate_by_session: dict[str, float] = field(default_factory=dict)
    win_rate_by_h4_bias: dict[str, float] = field(default_factory=dict)
    average_mfe: float = 0.0
    average_mae: float = 0.0
    average_r_multiple: float = 0.0
    overall_win_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _winrate(subset: pd.DataFrame) -> float:
    if subset.empty or "label" not in subset.columns:
        return 0.0
    resolved = subset[subset["label"].isin([0, 1])]
    if resolved.empty:
        return 0.0
    wins = (resolved["label"] == int(Label.TP_FIRST)).sum()
    return round(float(wins / len(resolved)), 4)


def _direction_label(direction: int) -> str:
    if direction > 0:
        return "buy"
    if direction < 0:
        return "sell"
    return "neutral"


def _session_from_row(row: pd.Series) -> str:
    if row.get("session_london", 0) == 1:
        return "london"
    if row.get("session_ny", 0) == 1:
        return "new_york"
    if row.get("session_asia", 0) == 1:
        return "asia"
    if row.get("session_off", 0) == 1:
        return "off_hours"
    return "unknown"


def _r_multiple_row(row: pd.Series) -> float:
    lbl = int(row.get("label", -1))
    if lbl == int(Label.TP_FIRST):
        return 2.0
    if lbl == int(Label.SL_FIRST):
        return -1.0
    return 0.0


def compute_dataset_statistics(df: pd.DataFrame, symbol: str, timeframe: str) -> DatasetStatistics:
    if df is None or df.empty:
        return DatasetStatistics(
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
        )

    labels = {
        "tp_first": int((df["label"] == int(Label.TP_FIRST)).sum()) if "label" in df.columns else 0,
        "sl_first": int((df["label"] == int(Label.SL_FIRST)).sum()) if "label" in df.columns else 0,
        "unresolved": int((df["label"] == int(Label.NO_RESOLUTION)).sum()) if "label" in df.columns else 0,
    }

    rows_per_event: dict[str, int] = {}
    events_stats: dict[str, dict[str, Any]] = {}
    if "event_type" in df.columns:
        for et, grp in df.groupby("event_type"):
            rows_per_event[str(et)] = int(len(grp))
            events_stats[str(et)] = {"count": int(len(grp)), "winrate": _winrate(grp)}

    rows_per_dir: dict[str, int] = {}
    if "direction" in df.columns:
        for d, grp in df.groupby("direction"):
            rows_per_dir[_direction_label(int(d))] = int(len(grp))

    split_dist: dict[str, int] = {}
    if "split" in df.columns:
        split_dist = {str(k): int(v) for k, v in df["split"].value_counts().items()}

    session_wr: dict[str, float] = {}
    if not df.empty:
        sessions = df.apply(_session_from_row, axis=1)
        work = df.copy()
        work["_session"] = sessions
        for sess, grp in work.groupby("_session"):
            session_wr[str(sess)] = _winrate(grp)

    h4_wr: dict[str, float] = {}
    if "h4_trend_bias" in df.columns:
        for bias, grp in df.groupby("h4_trend_bias"):
            h4_wr[str(int(bias))] = _winrate(grp)

    avg_mfe = float(df["mfe"].mean()) if "mfe" in df.columns else 0.0
    avg_mae = float(df["mae"].mean()) if "mae" in df.columns else 0.0
    r_multiples = df.apply(_r_multiple_row, axis=1) if "label" in df.columns else pd.Series(dtype=float)
    avg_r = float(r_multiples.mean()) if not r_multiples.empty else 0.0

    resolved = labels["tp_first"] + labels["sl_first"]
    overall_wr = round(labels["tp_first"] / resolved, 4) if resolved > 0 else 0.0

    return DatasetStatistics(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        rows=len(df),
        labels=labels,
        rows_per_event_type=rows_per_event,
        rows_per_direction=rows_per_dir,
        split_distribution=split_dist,
        events=events_stats,
        win_rate_by_session=session_wr,
        win_rate_by_h4_bias=h4_wr,
        average_mfe=round(avg_mfe, 6),
        average_mae=round(avg_mae, 6),
        average_r_multiple=round(avg_r, 6),
        overall_win_rate=overall_wr,
    )


def save_dataset_statistics(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    stats = compute_dataset_statistics(df, symbol, timeframe)
    path = dataset_statistics_report_path(symbol, timeframe, base_dir)
    path.write_text(json.dumps(stats.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
