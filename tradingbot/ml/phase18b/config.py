"""Phase 18B — controlled live gate configuration."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_DAYS = 365
DEFAULT_STRIDE = 5
DEFAULT_WARMUP = 350
STRIDES = (1, 5)

VERDICTS = (
    "NOT_READY_FOR_LIVE",
    "READY_FOR_LIMITED_LIVE",
    "READY_FOR_FULL_LIVE",
)

CHECK_STATUSES = ("PASS", "WARN", "FAIL")

PROTECTED_MODULES = (
    "tradingbot/kernel/trading_kernel.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/adapters/mt5_execution.py",
    "tradingbot/ml/decision_engine/decision_policy.py",
    "tradingbot/ml/research/regime_router/regime_router.py",
    "tradingbot/ml/feature_alignment/factory.py",
    "tradingbot/ml/confidence_mapping/production_adapter.py",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase18b"
