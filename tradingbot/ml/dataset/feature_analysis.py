"""Phase 8.2 feature quality analysis for production datasets."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_classif

from tradingbot.ml.data.paths import feature_quality_report_path, reports_dir
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.features.registry.registry import feature_names

NEAR_ZERO_VARIANCE = 1e-12


@dataclass
class FeatureAnalysisReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    features: dict[str, dict[str, float | bool]] = field(default_factory=dict)
    constant_features: list[str] = field(default_factory=list)
    near_zero_variance_features: list[str] = field(default_factory=list)
    missing_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label_correlation(series: pd.Series, labels: pd.Series) -> float:
    mask = labels.isin([int(Label.SL_FIRST), int(Label.TP_FIRST)])
    if mask.sum() < 3:
        return 0.0
    x = series[mask].astype(float)
    y = labels[mask].astype(float)
    if x.std() < NEAR_ZERO_VARIANCE:
        return 0.0
    corr = x.corr(y)
    return round(float(corr), 4) if not pd.isna(corr) else 0.0


def _mutual_information(
    df: pd.DataFrame,
    feature_cols: list[str],
) -> dict[str, float]:
    if "label" not in df.columns:
        return {c: 0.0 for c in feature_cols}

    resolved = df[df["label"].isin([int(Label.SL_FIRST), int(Label.TP_FIRST)])]
    if len(resolved) < 10:
        return {c: 0.0 for c in feature_cols}

    present = [c for c in feature_cols if c in resolved.columns]
    if not present:
        return {c: 0.0 for c in feature_cols}

    X = resolved[present].fillna(0.0).astype(float)
    y = resolved["label"].astype(int).values
    try:
        scores = mutual_info_classif(X, y, discrete_features=False, random_state=42)
        return {col: round(float(score), 4) for col, score in zip(present, scores)}
    except Exception:
        return {c: 0.0 for c in present}


def analyze_features(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> FeatureAnalysisReport:
    """Per-feature missing rate, variance, label correlation, and mutual information."""
    now = datetime.now(timezone.utc).isoformat()
    registered = feature_names()
    mi_scores = _mutual_information(df, registered) if df is not None and not df.empty else {}

    features: dict[str, dict[str, float | bool]] = {}
    constant: list[str] = []
    near_zero: list[str] = []
    missing_cols: list[str] = []

    for name in registered:
        if df is None or df.empty or name not in df.columns:
            missing_cols.append(name)
            features[name] = {
                "missing": 100.0,
                "variance": 0.0,
                "correlation": 0.0,
                "mutual_information": 0.0,
                "constant": True,
            }
            continue

        col = df[name]
        missing_pct = round(float(col.isna().mean() * 100), 2)
        filled = col.dropna().astype(float)
        variance = round(float(filled.var()), 6) if not filled.empty else 0.0
        is_constant = filled.nunique() <= 1
        is_near_zero = variance < NEAR_ZERO_VARIANCE and not is_constant

        if is_constant:
            constant.append(name)
        elif is_near_zero:
            near_zero.append(name)

        correlation = _label_correlation(col, df["label"]) if "label" in df.columns else 0.0
        features[name] = {
            "missing": missing_pct,
            "variance": variance,
            "correlation": correlation,
            "mutual_information": mi_scores.get(name, 0.0),
            "constant": is_constant,
        }

    return FeatureAnalysisReport(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        generated_at_utc=now,
        features=features,
        constant_features=constant,
        near_zero_variance_features=near_zero,
        missing_features=missing_cols,
    )


def save_feature_quality_report(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None = None,
) -> Path:
    reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
    report = analyze_features(df, symbol, timeframe)
    path = feature_quality_report_path(symbol, timeframe, base_dir)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
