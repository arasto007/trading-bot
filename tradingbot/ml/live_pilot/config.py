"""Phase 12 — live pilot configuration and mode gates."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

STRATEGY_A_THRESHOLDS = {"buy": 0.55, "sell": 0.45, "version": "A_original"}
STRATEGY_B_THRESHOLDS = {"buy": 0.50, "sell": 0.40, "version": "B_phase11_5_research"}

ALLOWED_REGIMES = frozenset({"RANGE", "LOW_VOLATILITY"})
SESSION_NAMES = ("asia", "london", "new_york", "overlap", "off_hours")


@dataclass
class PilotConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    mode: str = "SHADOW"  # SHADOW | PAPER | PILOT
    run_id: str = "v1"
    risk_pct: float = 0.0025
    max_open_positions: int = 1
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 3
    max_trades_per_day: int = 10
    pilot_days: int = 7
    poll_interval_sec: float = 30.0
    max_spread_pips: float = 8.0
    regime_filter_block: bool = False
    allowed_regimes: frozenset[str] = field(default_factory=lambda: ALLOWED_REGIMES)
    skip_preflight: bool = False
    skip_model_validation: bool = False
    seed: int = 42
    initial_balance: float = 10_000.0
    tp_r: float = 2.0
    sl_r: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "12",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "mode": self.mode,
            "run_id": self.run_id,
            "risk_pct": self.risk_pct,
            "max_open_positions": self.max_open_positions,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_trades_per_day": self.max_trades_per_day,
            "pilot_days": self.pilot_days,
            "strategy_a": STRATEGY_A_THRESHOLDS,
            "strategy_b": STRATEGY_B_THRESHOLDS,
            "allowed_regimes": sorted(self.allowed_regimes),
            "regime_filter_block": self.regime_filter_block,
        }


def resolve_mode(mode: str | None = None) -> str:
    explicit = (mode or os.environ.get("PHASE12_MODE", "SHADOW")).upper()
    if explicit not in ("SHADOW", "PAPER", "PILOT"):
        return "SHADOW"
    return explicit


def is_pilot_live_enabled() -> bool:
    return (
        os.environ.get("ENABLE_PHASE12_LIVE", "").lower() in ("1", "true", "yes")
        and os.environ.get("PILOT_APPROVAL", "").lower() in ("1", "true", "yes")
    )


def apply_mode_env(mode: str) -> None:
    """Configure process env for kernel shadow / pilot execution."""
    os.environ["ENABLE_ML_SHADOW"] = "true"
    if mode == "PILOT" and is_pilot_live_enabled():
        os.environ["ML_SHADOW_MODE"] = "false"
        os.environ.pop("TRADINGBOT_DRY_RUN", None)
        os.environ.pop("TRADINGBOT_PAPER", None)
    elif mode == "PAPER":
        os.environ["ML_SHADOW_MODE"] = "true"
        os.environ["TRADINGBOT_PAPER"] = "1"
        os.environ.pop("TRADINGBOT_DRY_RUN", None)
    else:
        os.environ["ML_SHADOW_MODE"] = "true"
        os.environ["TRADINGBOT_DRY_RUN"] = "1"
        os.environ.pop("TRADINGBOT_PAPER", None)


def signal_from_probability(prob: float, *, buy: float, sell: float) -> str:
    if prob >= buy:
        return "BUY"
    if prob <= sell:
        return "SELL"
    return "HOLD"


def ab_signals(probability: float | None) -> dict[str, Any]:
    if probability is None:
        return {"strategy_a": "HOLD", "strategy_b": "HOLD", "probability": None}
    p = float(probability)
    return {
        "probability": p,
        "strategy_a": signal_from_probability(
            p, buy=STRATEGY_A_THRESHOLDS["buy"], sell=STRATEGY_A_THRESHOLDS["sell"]
        ),
        "strategy_b": signal_from_probability(
            p, buy=STRATEGY_B_THRESHOLDS["buy"], sell=STRATEGY_B_THRESHOLDS["sell"]
        ),
        "threshold_a": STRATEGY_A_THRESHOLDS,
        "threshold_b": STRATEGY_B_THRESHOLDS,
    }


def session_for_hour(hour: int) -> list[str]:
    windows = {
        "asia": (0, 8),
        "london": (7, 16),
        "new_york": (13, 21),
        "overlap": (13, 16),
    }
    matched = [name for name, (start, end) in windows.items() if start <= hour < end]
    return matched or ["off_hours"]
