"""Phase 8.2 market regime analysis for production datasets (no model required)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import regime_report_path, reports_dir
from tradingbot.ml.dataset.schema import Label


@dataclass
class RegimeBucketMetrics:
    samples: int
    tp_rate: float
    win_rate: float
    avg_mfe: float
    avg_mae: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RegimeAnalysisReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    volatility: dict[str, dict[str, Any]] = field(default_factory=dict)
    trend: dict[str, dict[str, Any]] = field(default_factory=dict)
    market_condition: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_at_utc": self.generated_at_utc,
            "volatility": self.volatility,
            "trend": self.trend,
            "market_condition": self.market_condition,
        }


def _safe_col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        return df[name].fillna(default)
    return pd.Series(default, index=df.index)


def _bucket_metrics(subset: pd.DataFrame) -> RegimeBucketMetrics:
    n = len(subset)
    if n == 0 or "label" not in subset.columns:
        return RegimeBucketMetrics(0, 0.0, 0.0, 0.0, 0.0)

    tp = int((subset["label"] == int(Label.TP_FIRST)).sum())
    resolved = subset[subset["label"].isin([0, 1])]
    win_rate = round(tp / len(resolved), 4) if len(resolved) > 0 else 0.0
    mfe = round(float(subset["mfe"].mean()), 4) if "mfe" in subset.columns else 0.0
    mae = round(float(subset["mae"].mean()), 4) if "mae" in subset.columns else 0.0

    return RegimeBucketMetrics(
        samples=n,
        tp_rate=round(tp / n, 4),
        win_rate=win_rate,
        avg_mfe=mfe,
        avg_mae=mae,
    )


def analyze_regimes(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> RegimeAnalysisReport:
    """
    Performance by volatility_regime, trend_strength, and h4_trend_bias buckets.

    Does not load or train any ML model.
    """
    now = datetime.now(timezone.utc).isoformat()
    report = RegimeAnalysisReport(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=now,
    )

    if df is None or df.empty:
        return report

    vol = _safe_col(df, "volatility_regime", 0.5)
    trend = _safe_col(df, "trend_strength", 0.0)
    h4 = _safe_col(df, "h4_trend_bias", 0.0)

    vol_masks = {
        "low": vol <= 0.25,
        "medium": (vol > 0.25) & (vol < 0.75),
        "high": vol >= 0.75,
    }
    for name, mask in vol_masks.items():
        report.volatility[name] = _bucket_metrics(df[mask]).to_dict()

    trend_masks = {
        "weak": trend < 25,
        "moderate": (trend >= 25) & (trend < 50),
        "strong": trend >= 50,
    }
    for name, mask in trend_masks.items():
        report.trend[name] = _bucket_metrics(df[mask]).to_dict()

    condition_masks = {
        "bullish": h4 > 0.5,
        "neutral": h4.abs() <= 0.5,
        "bearish": h4 < -0.5,
    }
    for name, mask in condition_masks.items():
        report.market_condition[name] = _bucket_metrics(df[mask]).to_dict()

    return report


def save_regime_report(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    report = analyze_regimes(df, symbol, timeframe)
    path = regime_report_path(symbol, timeframe, base_dir)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
