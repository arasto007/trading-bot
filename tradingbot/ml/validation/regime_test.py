"""Market regime performance analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.training import load_model
from tradingbot.ml.validation._utils import load_resolved_dataset, write_json_report


@dataclass
class RegimeMetrics:
    expected_R: float
    winrate: float
    trades: int
    rows: int


@dataclass
class RegimeReport:
    model: str
    symbol: str
    timeframe: str
    threshold: float
    regimes: dict[str, RegimeMetrics] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "threshold": self.threshold,
            **{k: asdict(v) for k, v in self.regimes.items()},
        }


def _safe_col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        return df[name].fillna(default)
    return pd.Series(default, index=df.index)


def _regime_metrics(
    model: Any,
    subset: pd.DataFrame,
    feature_cols: list[str],
    threshold: float,
) -> RegimeMetrics:
    if subset.empty:
        return RegimeMetrics(0.0, 0.0, 0, 0)
    X = subset[feature_cols]
    y_true = np.asarray(subset["label"]).astype(int)
    proba = model.predict_proba(X)
    take = proba[:, 1] >= threshold
    n_trades = int(take.sum())
    if n_trades == 0:
        return RegimeMetrics(0.0, 0.0, 0, len(subset))
    winrate = float((y_true[take] == 1).mean())
    returns = np.where(y_true[take] == 1, 2.0, -1.0)
    return RegimeMetrics(
        expected_R=round(float(returns.mean()), 4),
        winrate=round(winrate, 4),
        trades=n_trades,
        rows=len(subset),
    )


def run_regime_analysis(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    threshold: float = 0.5,
    save: bool = True,
) -> RegimeReport:
    """
    Classify rows using ATR, trend_strength, volatility_regime, H4 bias.

    Regimes: trend, range, high_volatility, low_volatility.
    """
    df, feature_cols = load_resolved_dataset(symbol, timeframe, base_dir)
    model = load_model(model_name, base_dir)

    trend_strength = _safe_col(df, "trend_strength", 0.0)
    vol_regime = _safe_col(df, "volatility_regime", 0.5)
    atr_pct = _safe_col(df, "atr_percentile", 50.0)
    h4_bias = _safe_col(df, "h4_trend_bias", 0.0)

    masks = {
        "trend": trend_strength >= 25,
        "range": (trend_strength < 25) & (h4_bias.abs() < 0.5),
        "high_volatility": (vol_regime >= 0.75) | (atr_pct > 70),
        "low_volatility": (vol_regime <= 0.25) | (atr_pct < 30),
    }

    regimes: dict[str, RegimeMetrics] = {}
    for name, mask in masks.items():
        regimes[name] = _regime_metrics(model, df[mask], feature_cols, threshold)

    report = RegimeReport(
        model=model_name.lower(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        threshold=threshold,
        regimes=regimes,
    )

    if save:
        write_json_report(reports_dir(base_dir) / "regime_performance.json", report.to_dict())

    return report
