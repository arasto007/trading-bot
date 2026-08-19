"""Phase 20A — live deployment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"

# Capital control — Phase 1: small live exposure
DEFAULT_RISK_PCT = 0.02  # 2% of account per trade (within 1–5% band)
MIN_RISK_PCT = 0.01
MAX_RISK_PCT = 0.05
MAX_OPEN_POSITIONS = 1

# Hard safety thresholds
MAX_EXECUTION_FAILURES = 3
MAX_SIGNALS_PER_HOUR = 30
LATENCY_P95_LIMIT_MS = 100.0
LATENCY_SUSTAINED_CYCLES = 5
SHORT_WINDOW_DD_PCT = 0.10
EXECUTION_FAILURE_SPIKE = 3

VERDICT_STARTED = "LIVE_DEPLOYMENT_STARTED"

ENV_ENABLE_LIVE = "ENABLE_PHASE20A_LIVE"
ENV_APPROVAL = "PHASE20A_APPROVAL"


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase20a"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def is_live_execution_enabled() -> bool:
    return _env_bool(ENV_ENABLE_LIVE) and _env_bool(ENV_APPROVAL)


@dataclass
class DeploymentConfig:
    symbol: str = DEFAULT_SYMBOL
    timeframe: str = DEFAULT_TIMEFRAME
    risk_pct: float = DEFAULT_RISK_PCT
    max_open_positions: int = MAX_OPEN_POSITIONS
    max_trades_per_day: int = 20
    max_consecutive_losses: int = 4
    max_spread_pips: float = 8.0
    trend_version: str = "v41"
    enable_rsi_filter: bool = True
    enable_adx_filter: bool = True
    rsi_min: float = 40.0
    rsi_max: float = 60.0
    adx_min: float = 15.0
    adx_max: float = 50.0
    skip_certification_check: bool = False
    skip_preflight: bool = False
    base_dir: str | None = None

    def __post_init__(self) -> None:
        self.risk_pct = max(MIN_RISK_PCT, min(MAX_RISK_PCT, float(self.risk_pct)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "20A",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "risk_pct": self.risk_pct,
            "max_open_positions": self.max_open_positions,
            "max_trades_per_day": self.max_trades_per_day,
            "trend_model": "trend_rf_v41",
            "range_model": "phase9_9",
            "filters": {
                "rsi_mid": [self.rsi_min, self.rsi_max],
                "adx_band": [self.adx_min, self.adx_max],
            },
            "certification": "APPROVED_FOR_FULL_PRODUCTION",
        }


def apply_certified_env(cfg: DeploymentConfig) -> None:
    """Apply Phase 19D certified production environment."""
    os.environ["USE_ML_KERNEL"] = "true"
    os.environ["ENABLE_ML_SHADOW"] = "false"
    os.environ["ML_SHADOW_MODE"] = "false"
    os.environ.pop("TRADINGBOT_DRY_RUN", None)
    os.environ.pop("TRADINGBOT_PAPER", None)

    os.environ["TREND_MODEL_VERSION"] = cfg.trend_version
    os.environ["ENABLE_RSI_FILTER"] = "true" if cfg.enable_rsi_filter else "false"
    os.environ["ENABLE_ADX_FILTER"] = "true" if cfg.enable_adx_filter else "false"
    os.environ["RSI_MIN"] = str(cfg.rsi_min)
    os.environ["RSI_MAX"] = str(cfg.rsi_max)
    os.environ["ADX_MIN"] = str(cfg.adx_min)
    os.environ["ADX_MAX"] = str(cfg.adx_max)

    if is_live_execution_enabled():
        os.environ["ENABLE_PHASE12_LIVE"] = "true"
        os.environ["PILOT_APPROVAL"] = "true"
