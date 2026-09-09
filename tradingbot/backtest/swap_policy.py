"""Operator swap policy: BROKER_RATE_ONLY.

Broker-provided swap rates may be retained as evidence.
They must never be reinterpreted as a historical daily swap series.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    assess_cost_completeness,
    build_backtest_cost_model,
)
from tradingbot.backtest.dataset_provenance import compute_dataset_cost_status
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult

POLICY = "BROKER_RATE_ONLY"

# MT5 symbol_info.swap_rollover3days: 0=Sunday … 3=Wednesday.
MT5_ROLLOVER3DAYS_WEEKDAY = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
}


class SwapPolicyError(Exception):
    """Swap policy violation — fail closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BrokerSwapRateEvidence:
    symbol: str
    swap_long: float | None
    swap_short: float | None
    swap_rollover3days: int | None
    triple_swap_weekday: str | None
    evidence_class: str
    historical_swap_series: str
    source: str
    timestamp: str | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "swap_long": self.swap_long,
            "swap_short": self.swap_short,
            "swap_rollover3days": self.swap_rollover3days,
            "triple_swap_weekday": self.triple_swap_weekday,
            "evidence_class": self.evidence_class,
            "historical_swap_series": self.historical_swap_series,
            "source": self.source,
            "timestamp": self.timestamp,
            "note": self.note,
        }


def weekday_from_rollover3days(value: Any) -> str | None:
    """Map MT5 swap_rollover3days to a weekday only when the field is present."""
    if value is None or value == "":
        return None
    try:
        day = int(value)
    except (TypeError, ValueError):
        return None
    return MT5_ROLLOVER3DAYS_WEEKDAY.get(day)


def record_broker_swap_rates(
    spec: dict[str, Any],
    *,
    symbol: str = "XAUUSD_i",
    source: str = "",
    timestamp: str | None = None,
) -> BrokerSwapRateEvidence:
    """Retain broker spec rates as BROKER_RATE_ONLY evidence. No series synthesis."""
    long_rate = spec.get("swap_long")
    short_rate = spec.get("swap_short")
    rollover = spec.get("swap_rollover3days")
    weekday = weekday_from_rollover3days(rollover)
    has_rate = long_rate is not None or short_rate is not None
    return BrokerSwapRateEvidence(
        symbol=symbol,
        swap_long=float(long_rate) if long_rate is not None else None,
        swap_short=float(short_rate) if short_rate is not None else None,
        swap_rollover3days=int(rollover) if rollover is not None and str(rollover) != "" else None,
        triple_swap_weekday=weekday,
        evidence_class=POLICY if has_rate else "UNKNOWN",
        historical_swap_series="UNKNOWN",
        source=source,
        timestamp=timestamp,
        note=(
            "Broker-rate snapshot only. Not a historical daily swap series. "
            "Do not accrue these rates across backtest bars."
        ),
    )


def broker_rate_only_is_not_historical(evidence: BrokerSwapRateEvidence) -> bool:
    return (
        evidence.evidence_class == POLICY
        and evidence.historical_swap_series == "UNKNOWN"
    )


def realized_zero_is_not_verified_zero(realized_values: Iterable[float]) -> bool:
    """Short-hold realized 0.0 does not prove a zero-swap policy."""
    return not verified_zero_swap_from_realized(realized_values)


def verified_zero_swap_from_realized(realized_values: Iterable[float]) -> bool:
    """Never treat observed zero deal swap as verified universal zero."""
    values = list(realized_values)
    if values and all(v == 0.0 for v in values):
        return False
    return False


def synthesize_historical_swap_series(
    rates: BrokerSwapRateEvidence,
    *,
    bars: int,
    hold_days: int,
) -> list[float]:
    """Forbidden: current broker rates must not be projected into a historical series."""
    raise SwapPolicyError(
        "HISTORICAL_SERIES_FORBIDDEN",
        f"BROKER_RATE_ONLY forbids synthesizing {bars} bars / {hold_days} days from "
        f"swap_long={rates.swap_long} swap_short={rates.swap_short}",
    )


def historical_swap_accrual_allowed(swap_status: str) -> bool:
    """Accrual is allowed only for an actual HISTORICAL series — not broker-rate snapshots."""
    return str(swap_status).upper() == "HISTORICAL"


def cost_completeness_from_broker_rates_only() -> CostCompleteness:
    """Broker rates alone cannot make the cost contract COMPLETE."""
    cfg = BacktestConfig(
        spread_mode="PROXY",
        commission_status="ZERO",
        swap_status=POLICY,
        slippage_status="MODELED_PROXY",
    )
    return assess_cost_completeness(build_backtest_cost_model(cfg))


def dataset_completeness_from_broker_rate_swap() -> str:
    return compute_dataset_cost_status(
        spread_mode="DATASET",
        commission_status="OBSERVED",
        swap_status=POLICY,
        slippage_status="OBSERVED",
    )["cost_completeness"]


def cost_adjusted_blocked_when_historical_swap_unknown() -> bool:
    result = BacktestResult(
        config=BacktestConfig(swap_status=POLICY),
        initial_balance=1000.0,
        final_balance=1000.0,
        trades=[],
        equity_curve=[{"equity": 1000.0}],
    )
    metrics = compute_metrics(result, cost_completeness=cost_completeness_from_broker_rates_only())
    return not bool(metrics.get("cost_adjusted_metrics"))


def classify_swap_policy(
    *,
    swap_status: str,
    realized_values: Iterable[float] | None = None,
    historical_series_present: bool = False,
) -> dict[str, Any]:
    status = str(swap_status).upper()
    realized = list(realized_values or [])
    return {
        "policy": POLICY,
        "configured_status": status,
        "is_broker_rate_only": status == POLICY,
        "is_historical": status == "HISTORICAL" and historical_series_present,
        "historical_swap_series": "PRESENT" if historical_series_present else "UNKNOWN",
        "broker_rate_only_equals_historical": False,
        "realized_zero_proves_verified_zero": verified_zero_swap_from_realized(realized),
        "accrual_allowed": historical_swap_accrual_allowed(status) and historical_series_present,
        "cost_adjusted_allowed": False if not historical_series_present and status in (POLICY, "UNKNOWN") else None,
    }
