"""Robustness testing under market conditions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.training import load_model
from tradingbot.ml.validation._utils import (
    load_resolved_dataset,
    stability_score,
    write_json_report,
)


@dataclass
class ConditionResult:
    condition: str
    rows: int
    expected_R: float
    winrate: float
    number_of_trades: int
    stability: float


@dataclass
class RobustnessReport:
    model: str
    symbol: str
    timeframe: str
    threshold: float
    conditions: list[ConditionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        return df[name].fillna(default)
    return pd.Series(default, index=df.index)


def _condition_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    atr_pct = _safe_col(df, "atr_percentile", 50.0)
    vol_regime = _safe_col(df, "volatility_regime", 0.5)
    trend_strength = _safe_col(df, "trend_strength", 0.0)

    return {
        "high_volatility": (vol_regime >= 0.75) | (atr_pct > 70),
        "low_volatility": (vol_regime <= 0.25) | (atr_pct < 30),
        "london_session": _safe_col(df, "session_london", 0.0) >= 0.5,
        "new_york_session": _safe_col(df, "session_ny", 0.0) >= 0.5,
        "asia_session": _safe_col(df, "session_asia", 0.0) >= 0.5,
        "trending_market": trend_strength >= 25,
        "ranging_market": trend_strength < 20,
    }


def _evaluate_subset(
    model: Any,
    subset: pd.DataFrame,
    feature_cols: list[str],
    threshold: float,
) -> tuple[float, float, int]:
    if subset.empty:
        return 0.0, 0.0, 0
    X = subset[feature_cols]
    y_true = np.asarray(subset["label"]).astype(int)
    proba = model.predict_proba(X)
    take = proba[:, 1] >= threshold
    n_trades = int(take.sum())
    if n_trades == 0:
        return 0.0, 0.0, 0
    winrate = float((y_true[take] == 1).mean())
    returns = np.where(y_true[take] == 1, 2.0, -1.0)
    expected_r = float(returns.mean())
    return round(expected_r, 4), round(winrate, 4), n_trades


def run_robustness_tests(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    threshold: float = 0.5,
    save: bool = True,
) -> RobustnessReport:
    df, feature_cols = load_resolved_dataset(symbol, timeframe, base_dir)
    model = load_model(model_name, base_dir)
    masks = _condition_masks(df)

    results: list[ConditionResult] = []
    for name, mask in masks.items():
        subset = df[mask]
        exp_r, winrate, n_trades = _evaluate_subset(model, subset, feature_cols, threshold)
        # Stability: consistency of rolling expected R across chunks of the subset
        chunk_scores: list[float] = []
        if len(subset) >= 20:
            chunk_size = max(10, len(subset) // 5)
            for start in range(0, len(subset) - chunk_size + 1, chunk_size):
                chunk = subset.iloc[start : start + chunk_size]
                cr, _, _ = _evaluate_subset(model, chunk, feature_cols, threshold)
                chunk_scores.append(cr)
        stab = stability_score(chunk_scores) if chunk_scores else 0.0

        results.append(
            ConditionResult(
                condition=name,
                rows=len(subset),
                expected_R=exp_r,
                winrate=winrate,
                number_of_trades=n_trades,
                stability=stab,
            )
        )

    report = RobustnessReport(
        model=model_name.lower(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        threshold=threshold,
        conditions=results,
    )

    if save:
        write_json_report(reports_dir(base_dir) / "robustness_report.json", report.to_dict())

    return report
