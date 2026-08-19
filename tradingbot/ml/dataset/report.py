"""Dataset quality report generation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import dataset_quality_report_path, reports_dir
from tradingbot.ml.dataset.validation import validate_dataset


@dataclass
class DatasetQualityReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    sample_count: int
    win_rate: float
    label_distribution: dict[str, int] = field(default_factory=dict)
    event_distribution: dict[str, int] = field(default_factory=dict)
    missing_values_pct: float = 0.0
    duplicate_samples: int = 0
    date_coverage: dict[str, str | None] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_dataset_quality_report(df: pd.DataFrame, symbol: str, timeframe: str) -> DatasetQualityReport:
    validation = validate_dataset(df)
    label_dist = validation.label_distribution
    wins = label_dist.get("1", 0)
    losses = label_dist.get("0", 0)
    resolved = wins + losses
    win_rate = round(wins / resolved, 4) if resolved > 0 else 0.0

    dup = 0
    if "event_id" in df.columns:
        dup = int(df.duplicated(subset=["event_id"]).sum())

    missing_pct = 0.0
    if not df.empty:
        missing_pct = round(float(df.isna().mean().mean() * 100), 4)

    date_cov: dict[str, str | None] = {"start": None, "end": None}
    if "timestamp" in df.columns and not df.empty:
        ts = pd.to_datetime(df["timestamp"], utc=True)
        date_cov["start"] = ts.min().isoformat()
        date_cov["end"] = ts.max().isoformat()

    return DatasetQualityReport(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        sample_count=len(df),
        win_rate=win_rate,
        label_distribution=label_dist,
        event_distribution=validation.event_distribution,
        missing_values_pct=missing_pct,
        duplicate_samples=dup,
        date_coverage=date_cov,
        validation=validation.to_dict(),
    )


def save_dataset_quality_report(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    report = build_dataset_quality_report(df, symbol, timeframe)
    path = dataset_quality_report_path(symbol, timeframe, base_dir)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
