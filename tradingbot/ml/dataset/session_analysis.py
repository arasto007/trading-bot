"""Phase 8.2 session breakdown analysis for production datasets."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import reports_dir, session_report_path
from tradingbot.ml.dataset.schema import Label

SESSION_COLUMNS: tuple[str, ...] = ("session_asia", "session_london", "session_ny")


@dataclass
class SessionMetrics:
    samples: int
    tp_rate: float
    sl_rate: float
    no_resolution_rate: float
    win_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionAnalysisReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_at_utc": self.generated_at_utc,
            "sessions": self.sessions,
        }


def _session_metrics(subset: pd.DataFrame) -> SessionMetrics:
    n = len(subset)
    if n == 0:
        return SessionMetrics(0, 0.0, 0.0, 0.0, 0.0)

    tp = int((subset["label"] == int(Label.TP_FIRST)).sum())
    sl = int((subset["label"] == int(Label.SL_FIRST)).sum())
    nr = int((subset["label"] == int(Label.NO_RESOLUTION)).sum())
    resolved = tp + sl
    win_rate = round(tp / resolved, 4) if resolved > 0 else 0.0

    return SessionMetrics(
        samples=n,
        tp_rate=round(tp / n, 4),
        sl_rate=round(sl / n, 4),
        no_resolution_rate=round(nr / n, 4),
        win_rate=win_rate,
    )


def analyze_sessions(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> SessionAnalysisReport:
    """Analyze samples and label performance per trading session."""
    now = datetime.now(timezone.utc).isoformat()
    report = SessionAnalysisReport(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=now,
    )

    if df is None or df.empty or "label" not in df.columns:
        return report

    for col in SESSION_COLUMNS:
        if col not in df.columns:
            continue
        name = col.replace("session_", "").capitalize()
        active = df[df[col] == 1]
        metrics = _session_metrics(active)
        report.sessions[name] = metrics.to_dict()

    return report


def save_session_report(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    report = analyze_sessions(df, symbol, timeframe)
    path = session_report_path(symbol, timeframe, base_dir)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
