"""Phase 13.6 — shared optimizer types and scoring (no backtest imports)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

ATR_EXTREME = 95.0
SPREAD_ABNORMAL = 8.0
EMA_SLOPE_STRONG = 0.15


@dataclass(frozen=True)
class RegimeThresholdParams:
    adx_trend_min: float = 25.0
    adx_range_max: float = 20.0
    atr_low_vol: float = 30.0
    atr_high_vol: float = 90.0


@dataclass(frozen=True)
class OptimizerConfig:
    regime_params: RegimeThresholdParams
    range_buy_threshold: float = 0.55
    range_sell_threshold: float = 0.45
    trend_ml_threshold: float = 0.55
    policy: str = "A"
    min_confidence: float = 0.0
    symbol: str = "XAUUSD"
    seed: int = 42


def classify_regime_row(row: pd.Series, params: RegimeThresholdParams) -> str:
    """Tunable copy of Phase 13.2 rules — does not modify regime_detector."""
    spread = float(row.get("spread_pips", 0.0))
    atr_pct = float(row.get("atr_percentile", 50.0))
    adx = float(row.get("adx", row.get("trend_strength", 0.0)))
    ema50_slope = float(row.get("ema50_slope", 0.0))
    volatility = float(row.get("volatility", 0.0))

    if spread >= SPREAD_ABNORMAL or atr_pct >= ATR_EXTREME or volatility >= 5.0:
        return "NO_TRADE"
    if atr_pct > params.atr_high_vol:
        return "HIGH_VOLATILITY"
    if adx > params.adx_trend_min and abs(ema50_slope) >= EMA_SLOPE_STRONG:
        return "TREND"
    if adx < params.adx_range_max and atr_pct < params.atr_low_vol:
        return "RANGE"
    if adx > params.adx_trend_min:
        return "TREND"
    return "RANGE"


def classify_regimes(frame: pd.DataFrame, params: RegimeThresholdParams) -> pd.Series:
    return frame.apply(lambda row: classify_regime_row(row, params), axis=1)


def composite_score(
    metrics: dict[str, Any],
    *,
    robustness: float = 0.5,
    overfit_penalty: float = 0.0,
) -> float:
    pf = min(float(metrics.get("profit_factor", 0.0)), 3.0) / 3.0
    exp = min(max(float(metrics.get("expectancy", metrics.get("expectancy_r", 0.0))) + 1.0, 0.0), 2.0) / 2.0
    dd = 1.0 - min(float(metrics.get("max_drawdown", 1.0)), 1.0)
    return round(pf * 0.35 + exp * 0.30 + robustness * 0.20 + dd * 0.15 - overfit_penalty, 4)


def config_to_dict(config: OptimizerConfig) -> dict[str, Any]:
    return {
        "policy": config.policy,
        "range_buy_threshold": config.range_buy_threshold,
        "range_sell_threshold": config.range_sell_threshold,
        "trend_ml_threshold": config.trend_ml_threshold,
        "min_confidence": config.min_confidence,
        "regime_params": {
            "adx_trend_min": config.regime_params.adx_trend_min,
            "adx_range_max": config.regime_params.adx_range_max,
            "atr_low_vol": config.regime_params.atr_low_vol,
        },
    }


def baseline_phase135_config() -> OptimizerConfig:
    return OptimizerConfig(
        regime_params=RegimeThresholdParams(),
        range_buy_threshold=0.55,
        range_sell_threshold=0.45,
        trend_ml_threshold=0.55,
        policy="A",
    )


def ml_threshold_pair(threshold: float) -> tuple[float, float]:
    """Map ML cutoff to Phase 9.9 buy/sell pair with fixed 0.10 spread."""
    buy = round(float(threshold), 2)
    sell = round(max(0.05, buy - 0.10), 2)
    if sell >= buy:
        buy = round(sell + 0.05, 2)
    return buy, sell
