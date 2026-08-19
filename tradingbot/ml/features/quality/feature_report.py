"""Feature quality and correlation reporting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import feature_correlation_report_path, feature_quality_report_path, reports_dir
from tradingbot.ml.features.quality.feature_validator import FeatureValidationResult, validate_feature_dataframe
from tradingbot.ml.features.registry.registry import feature_names


@dataclass
class FeatureQualityReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    validation: dict[str, Any]
    zero_information_features: list[str] = field(default_factory=list)
    constant_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureCorrelationReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    correlation_threshold: float
    highly_correlated_pairs: list[dict[str, Any]] = field(default_factory=list)
    redundant_features: list[str] = field(default_factory=list)
    zero_information_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _zero_information_features(df: pd.DataFrame, cols: list[str]) -> list[str]:
    out: list[str] = []
    for col in cols:
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if s.empty or s.nunique() <= 1:
            out.append(col)
    return out


def build_quality_report(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    reference_df: pd.DataFrame | None = None,
) -> FeatureQualityReport:
    validation = validate_feature_dataframe(df, reference_df=reference_df)
    cols = [c for c in feature_names() if c in df.columns]
    constants = [c for c in cols if validation.per_feature.get(c, {}).get("constant")]
    zero_info = _zero_information_features(df, cols)
    return FeatureQualityReport(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        validation=validation.to_dict(),
        zero_information_features=zero_info,
        constant_features=constants,
    )


def build_correlation_report(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    threshold: float = 0.92,
) -> FeatureCorrelationReport:
    cols = [c for c in feature_names() if c in df.columns]
    zero_info = _zero_information_features(df, cols)
    active = [c for c in cols if c not in zero_info]
    pairs: list[dict[str, Any]] = []
    redundant: set[str] = set()

    if len(active) >= 2:
        corr = df[active].corr().abs()
        for i, a in enumerate(active):
            for b in active[i + 1 :]:
                val = float(corr.loc[a, b]) if not np.isnan(corr.loc[a, b]) else 0.0
                if val >= threshold:
                    pairs.append({"feature_a": a, "feature_b": b, "correlation": round(val, 4)})
                    redundant.add(b)

    return FeatureCorrelationReport(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        correlation_threshold=threshold,
        highly_correlated_pairs=sorted(pairs, key=lambda x: -x["correlation"]),
        redundant_features=sorted(redundant),
        zero_information_features=zero_info,
    )


def save_reports(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
    *,
    reference_df: pd.DataFrame | None = None,
    correlation_threshold: float = 0.92,
) -> dict[str, Path]:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    quality = build_quality_report(df, symbol, timeframe, reference_df=reference_df)
    correlation = build_correlation_report(df, symbol, timeframe, threshold=correlation_threshold)

    q_path = feature_quality_report_path(symbol, timeframe, base_dir)
    c_path = feature_correlation_report_path(symbol, timeframe, base_dir)
    q_path.write_text(json.dumps(quality.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    c_path.write_text(json.dumps(correlation.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return {"feature_quality": q_path, "feature_correlation": c_path}
