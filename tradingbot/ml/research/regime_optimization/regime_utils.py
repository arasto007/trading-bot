"""Phase 9.6 — shared regime research utilities."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.training.evaluation import label_r_outcomes, max_drawdown_proxy, profit_factor

REGIMES: tuple[str, ...] = (
    "TREND_UP",
    "TREND_DOWN",
    "RANGE",
    "HIGH_VOLATILITY",
    "LOW_VOLATILITY",
)

EVENT_SCHEMES: dict[str, tuple[str, ...] | None] = {
    "A_all_events": None,
    "B_order_block_only": ("order_block",),
    "C_choch_only": ("choch",),
    "D_order_block_choch": ("order_block", "choch"),
    "E_liquidity_order_block": ("liquidity_sweep", "order_block"),
}

EVENT_TYPES: tuple[str, ...] = (
    "order_block",
    "choch",
    "liquidity_sweep",
    "fvg",
    "bos",
    "session_transition",
)

TP_R = 2.0
SL_R = 1.0


def _col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return df[name].astype(float).fillna(default)


def assign_market_regime(df: pd.DataFrame) -> pd.Series:
    """Point-in-time regime classification using only causal registry features."""
    trend = _col(df, "trend_strength", 0.0)
    ema_cross = _col(df, "ema_cross_state", 0.0)
    atr_pct = _col(df, "atr_percentile", 50.0)
    vol_regime = _col(df, "volatility_regime", 0.5)
    ema_slope = _col(df, "ema50_slope", 0.0)
    h4_bias = _col(df, "h4_trend_bias", 0.0)

    regimes = np.full(len(df), "RANGE", dtype=object)
    high_vol = (atr_pct > 70) | (vol_regime >= 1.0)
    low_vol = (atr_pct < 30) | (vol_regime <= 0.0)
    regimes[high_vol] = "HIGH_VOLATILITY"
    regimes[low_vol & ~high_vol] = "LOW_VOLATILITY"

    trend_up = (trend > 25) & (ema_cross > 0) & (ema_slope > 0) & (h4_bias >= 0)
    trend_down = (trend > 25) & (ema_cross < 0) & (ema_slope < 0) & (h4_bias <= 0)
    mask_neutral = ~(high_vol | low_vol)
    regimes[mask_neutral & trend_up] = "TREND_UP"
    regimes[mask_neutral & trend_down] = "TREND_DOWN"
    return pd.Series(regimes, index=df.index)


def apply_event_filter(df: pd.DataFrame, scheme: str) -> pd.DataFrame:
    events = EVENT_SCHEMES.get(scheme)
    if events is None:
        return df
    return df.loc[df["event_type"].isin(events)].copy()


def trading_metrics_from_labels(y: np.ndarray) -> dict[str, float]:
    y = np.asarray(y).astype(int)
    if len(y) == 0:
        return {
            "win_rate": 0.0,
            "expectancy": 0.0,
            "average_R": 0.0,
            "profit_factor_proxy": 0.0,
            "max_drawdown_proxy": 0.0,
        }
    outcomes = label_r_outcomes(y)
    wins = int((y == int(Label.TP_FIRST)).sum())
    resolved = len(y)
    return {
        "win_rate": round(wins / resolved, 4) if resolved else 0.0,
        "expectancy": round(float(outcomes.mean()), 4),
        "average_R": round(float(outcomes.mean()), 4),
        "profit_factor_proxy": round(profit_factor(outcomes), 4),
        "max_drawdown_proxy": round(max_drawdown_proxy(outcomes), 4),
    }


def metrics_block(y_true: np.ndarray, y_pred: np.ndarray, proba: np.ndarray | None = None) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)
    ml: dict[str, float] = {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": 0.0,
    }
    if proba is not None and len(np.unique(y_true)) > 1:
        ml["roc_auc"] = round(float(roc_auc_score(y_true, proba[:, 1])), 4)
    trading = trading_metrics_from_labels(y_true)
    return {"classification": ml, "trading": trading}
