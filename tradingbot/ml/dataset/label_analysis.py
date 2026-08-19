"""Phase 8.2 label distribution analysis for production datasets."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import label_quality_report_path, reports_dir
from tradingbot.ml.dataset.schema import Label


@dataclass
class LabelDistributionReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    total_samples: int
    class_distribution: dict[str, int] = field(default_factory=dict)
    class_percentages: dict[str, float] = field(default_factory=dict)
    imbalance_ratio: float = 0.0
    invalid_labels: int = 0
    win_rate: float = 0.0
    status: str = "healthy"
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _balance_status(tp_rate: float) -> str:
    if 0.45 <= tp_rate <= 0.55:
        return "healthy"
    if 0.35 <= tp_rate <= 0.65:
        return "acceptable"
    return "warning"


def analyze_label_distribution(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> LabelDistributionReport:
    """Analyze label column: 0=SL_FIRST, 1=TP_FIRST, -1=NO_RESOLUTION."""
    now = datetime.now(timezone.utc).isoformat()
    if df is None or df.empty or "label" not in df.columns:
        return LabelDistributionReport(
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            generated_at_utc=now,
            total_samples=0,
            status="warning",
            issues=["empty dataset or missing label column"],
        )

    labels = df["label"]
    valid_mask = labels.isin([int(Label.SL_FIRST), int(Label.TP_FIRST), int(Label.NO_RESOLUTION)])
    invalid = int((~valid_mask).sum())

    dist = {str(int(k)): int(v) for k, v in labels.value_counts().items()}
    total = len(df)
    pct = {k: round(v / total * 100, 2) for k, v in dist.items()}

    tp = int(dist.get("1", 0))
    sl = int(dist.get("0", 0))
    resolved = tp + sl
    win_rate = round(tp / resolved, 4) if resolved > 0 else 0.0
    imbalance = round(min(tp, sl) / max(tp, sl), 4) if resolved > 0 and max(tp, sl) > 0 else 0.0

    status = _balance_status(win_rate)
    issues: list[str] = []
    if invalid > 0:
        issues.append(f"{invalid} invalid label values")
        status = "warning"
    if resolved == 0:
        issues.append("no resolved labels (0/1)")
        status = "warning"

    return LabelDistributionReport(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=now,
        total_samples=total,
        class_distribution=dist,
        class_percentages=pct,
        imbalance_ratio=imbalance,
        invalid_labels=invalid,
        win_rate=win_rate,
        status=status,
        issues=issues,
    )


def save_label_quality_report(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    report = analyze_label_distribution(df, symbol, timeframe)
    path = label_quality_report_path(symbol, timeframe, base_dir)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
