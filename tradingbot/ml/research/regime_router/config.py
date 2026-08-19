"""Phase 13.5 — regime router configuration (research only)."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_RISK_PCT = 0.005
DEFAULT_RR_RATIO = 2.0
DEFAULT_TREND_ML_THRESHOLD = 0.55
WALK_FORWARD_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025, 2026)
MAX_HOLD_BARS = 72


@dataclass(frozen=True)
class RouterConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    seed: int = 42
    risk_pct: float = DEFAULT_RISK_PCT
    rr_ratio: float = DEFAULT_RR_RATIO
    trend_ml_threshold: float = DEFAULT_TREND_ML_THRESHOLD
    phase9_9_model_version: str = "phase9_9_best"
    trend_ml_model_version: str = "phase13_4_trend_ml_logistic"
