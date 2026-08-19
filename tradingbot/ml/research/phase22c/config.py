"""Phase 22C — profitability recovery tunables (env-driven, safety preserved)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Phase22CConfig:
    """Recovery settings — lower HOLD rate without disabling RiskGate / SL / Meta."""

    enabled: bool = True
    decision_min_confidence: float = 0.48
    quality_threshold: float = 0.52
    calibration_min_confidence: float = 0.42
    range_buy_threshold: float = 0.52
    range_sell_threshold: float = 0.48
    rsi_min: float = 35.0
    rsi_max: float = 65.0
    adx_min: float = 10.0
    adx_max: float = 55.0
    daily_loss_floor_trades: int = 3
    use_day_start_balance: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "decision_min_confidence": self.decision_min_confidence,
            "quality_threshold": self.quality_threshold,
            "calibration_min_confidence": self.calibration_min_confidence,
            "range_buy_threshold": self.range_buy_threshold,
            "range_sell_threshold": self.range_sell_threshold,
            "rsi_min": self.rsi_min,
            "rsi_max": self.rsi_max,
            "adx_min": self.adx_min,
            "adx_max": self.adx_max,
            "daily_loss_floor_trades": self.daily_loss_floor_trades,
            "use_day_start_balance": self.use_day_start_balance,
        }


def load_phase22c_config() -> Phase22CConfig:
    return Phase22CConfig(
        enabled=_env_bool("PHASE22C_ENABLED", True),
        decision_min_confidence=_env_float("PHASE22C_DECISION_MIN_CONFIDENCE", 0.48),
        quality_threshold=_env_float("PHASE22C_QUALITY_THRESHOLD", 0.52),
        calibration_min_confidence=_env_float("PHASE22C_CALIBRATION_MIN_CONFIDENCE", 0.42),
        range_buy_threshold=_env_float("PHASE22C_RANGE_BUY_THRESHOLD", 0.52),
        range_sell_threshold=_env_float("PHASE22C_RANGE_SELL_THRESHOLD", 0.48),
        rsi_min=_env_float("PHASE22C_RSI_MIN", 35.0),
        rsi_max=_env_float("PHASE22C_RSI_MAX", 65.0),
        adx_min=_env_float("PHASE22C_ADX_MIN", 10.0),
        adx_max=_env_float("PHASE22C_ADX_MAX", 55.0),
        daily_loss_floor_trades=int(_env_float("PHASE22C_DAILY_LOSS_FLOOR_TRADES", 3)),
        use_day_start_balance=_env_bool("PHASE22C_USE_DAY_START_BALANCE", True),
    )


def compute_daily_loss_budget(
    *,
    reference_balance: float,
    max_daily_loss_pct: float,
    risk_per_trade: float,
    floor_trades: int,
) -> float:
    """
    Proportional daily loss budget in account currency.

    Keeps pct-based cap but floors budget so small accounts are not stopped
    after one oversized loss relative to planned per-trade risk.
    """
    ref = max(reference_balance, 0.0)
    pct_cap = ref * max_daily_loss_pct
    risk_unit = ref * risk_per_trade
    floor = risk_unit * max(1, floor_trades)
    return max(pct_cap, floor)
