"""Operator commission policy: VERIFIED_SCHEDULE.

Commission may be accepted for validation only when a verified,
account-applicable schedule exists. Observed zero on deals is not
that schedule. A generic public broker page is supporting evidence
only, never automatically account-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

POLICY = "VERIFIED_SCHEDULE"
OBSERVED_ZERO_NOT_PROVEN = "OBSERVED_ZERO_NOT_PROVEN"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"

REQUIRED_APPLICABILITY_FIELDS = (
    "broker",
    "server",
    "account_type",
    "asset_class",
    "symbol",
    "basis",
    "currency",
    "effective_date_or_version",
)

# Phase 27.19: account/product applicability is required in addition to 27.12 fields.
ACCOUNT_APPLICABILITY_EXTRA_FIELDS = ("account_product_type",)

ALLOWED_BASIS = frozenset({"per_lot", "per_side", "round_turn"})


class CommissionPolicyError(Exception):
    """Commission policy violation — fail closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CommissionSchedule:
    broker: str | None = None
    server: str | None = None
    account_type: str | None = None
    asset_class: str | None = None
    symbol: str | None = None
    basis: str | None = None
    currency: str | None = None
    effective_date_or_version: str | None = None
    rate: float | None = None
    source: str = ""
    source_class: str = UNKNOWN
    applicability_established: bool = False
    applicability_conditions: tuple[str, ...] = ()
    public_supporting_only: bool = False
    account_product_type: str | None = None
    account_environment: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "broker": self.broker,
            "server": self.server,
            "account_type": self.account_type,
            "account_environment": self.account_environment or self.account_type,
            "account_product_type": self.account_product_type,
            "asset_class": self.asset_class,
            "symbol": self.symbol,
            "basis": self.basis,
            "currency": self.currency,
            "effective_date_or_version": self.effective_date_or_version,
            "rate": self.rate,
            "source": self.source,
            "source_class": self.source_class,
            "applicability_established": self.applicability_established,
            "applicability_conditions": list(self.applicability_conditions),
            "public_supporting_only": self.public_supporting_only,
            "note": self.note,
        }


@dataclass(frozen=True)
class ObservedCommissionClassification:
    status: str
    sample_count: int
    observed_zero_count: int
    observed_nonzero_count: int
    observed_values: tuple[float, ...] = field(default_factory=tuple)
    proves_verified_schedule: bool = False
    proves_universal_zero: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "sample_count": self.sample_count,
            "observed_zero_count": self.observed_zero_count,
            "observed_nonzero_count": self.observed_nonzero_count,
            "observed_values_preview": list(self.observed_values[:8]),
            "proves_verified_schedule": self.proves_verified_schedule,
            "proves_universal_zero": self.proves_universal_zero,
            "note": self.note,
        }


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip() not in ("", "UNKNOWN", "NOT COLLECTED", "N/A", "NONE")


def observed_zero_is_not_verified_schedule(values: Iterable[float] | None = None) -> bool:
    """Any all-zero deal tape is not a verified commission schedule."""
    return not observed_zero_is_verified_schedule(values)


def observed_zero_is_verified_schedule(values: Iterable[float] | None = None) -> bool:
    """Never treat observed zeros as a verified schedule, regardless of count."""
    list(values or [])
    return False


def classify_observed_commissions(values: Iterable[float]) -> ObservedCommissionClassification:
    nums = [float(v) for v in values]
    zeros = sum(1 for v in nums if v == 0.0)
    nonzero = sum(1 for v in nums if v != 0.0)
    if not nums:
        status = UNKNOWN
        note = "no observed commission values"
    elif nonzero == 0:
        status = OBSERVED_ZERO_NOT_PROVEN
        note = (
            f"{len(nums)} gold deal(s) show commission=0.0. "
            "Observed zero is not a verified schedule and does not prove universal zero."
        )
    else:
        status = "OBSERVED_NONZERO_NOT_SCHEDULE"
        note = (
            f"{len(nums)} deal(s) include nonzero commission; still not an account-applicable "
            "verified schedule without provenance and applicability."
        )
    return ObservedCommissionClassification(
        status=status,
        sample_count=len(nums),
        observed_zero_count=zeros,
        observed_nonzero_count=nonzero,
        observed_values=tuple(nums),
        proves_verified_schedule=False,
        proves_universal_zero=False,
        note=note,
    )


def generic_public_schedule_is_account_specific(
    schedule: CommissionSchedule | dict[str, Any] | None,
) -> bool:
    """A generic public broker page is never automatically account-specific."""
    if schedule is None:
        return False
    data = schedule.to_dict() if isinstance(schedule, CommissionSchedule) else dict(schedule)
    if data.get("public_supporting_only"):
        return False
    if str(data.get("source_class") or "").upper() in ("PUBLIC", "GENERIC_PUBLIC", "PUBLIC_SUPPORTING"):
        return False
    return False


def missing_applicability_fields(schedule: CommissionSchedule | dict[str, Any]) -> list[str]:
    data = schedule.to_dict() if isinstance(schedule, CommissionSchedule) else dict(schedule)
    missing = [name for name in REQUIRED_APPLICABILITY_FIELDS if not _nonempty(data.get(name))]
    basis = data.get("basis")
    if _nonempty(basis) and str(basis) not in ALLOWED_BASIS:
        missing.append("basis")
    if not bool(data.get("applicability_established")):
        missing.append("applicability_established")
    return missing


def missing_account_applicability_fields(schedule: CommissionSchedule | dict[str, Any]) -> list[str]:
    """27.19: 27.12 fields plus account/product type."""
    missing = missing_applicability_fields(schedule)
    data = schedule.to_dict() if isinstance(schedule, CommissionSchedule) else dict(schedule)
    for name in ACCOUNT_APPLICABILITY_EXTRA_FIELDS:
        if not _nonempty(data.get(name)):
            missing.append(name)
    return missing


def broker_name_match_is_not_account_verification(
    schedule: CommissionSchedule | dict[str, Any] | None = None,
    account_broker: str | None = None,
) -> bool:
    """A matching broker name is never account-specific verification."""
    _ = schedule
    _ = account_broker
    return True


def commission_per_lot_zero_is_not_explicit_zero(commission_per_lot: float, commission_status: str) -> bool:
    """BacktestConfig.commission_per_lot=0.0 is not CostAvailability.ZERO."""
    return float(commission_per_lot) == 0.0 and str(commission_status).upper() != "ZERO"


def verified_schedule_requires_applicability(
    schedule: CommissionSchedule | dict[str, Any] | None,
) -> bool:
    """True only when every applicability field is present and explicitly established."""
    if schedule is None:
        return False
    return not missing_applicability_fields(schedule)


def accept_verified_schedule(schedule: CommissionSchedule | dict[str, Any]) -> CommissionSchedule:
    """Accept a schedule only when applicability to this account context is established."""
    data = schedule.to_dict() if isinstance(schedule, CommissionSchedule) else dict(schedule)
    if data.get("public_supporting_only") or generic_public_schedule_is_account_specific(data):
        raise CommissionPolicyError(
            "GENERIC_PUBLIC_NOT_ACCOUNT_SPECIFIC",
            "Public/generic commission documentation is supporting evidence only "
            "and is not an account-specific verified schedule.",
        )
    missing = missing_applicability_fields(data)
    if missing:
        raise CommissionPolicyError(
            "APPLICABILITY_REQUIRED",
            "Verified schedule rejected; missing applicability: " + ", ".join(missing),
        )
    if data.get("rate") is None:
        raise CommissionPolicyError(
            "SCHEDULE_RATE_REQUIRED",
            "Verified schedule rejected; rate is missing after applicability checks.",
        )
    return CommissionSchedule(
        broker=str(data.get("broker")),
        server=str(data.get("server")),
        account_type=str(data.get("account_type")),
        account_environment=str(data.get("account_environment") or data.get("account_type")),
        account_product_type=str(data.get("account_product_type")) if _nonempty(data.get("account_product_type")) else None,
        asset_class=str(data.get("asset_class")),
        symbol=str(data.get("symbol")),
        basis=str(data.get("basis")),
        currency=str(data.get("currency")),
        effective_date_or_version=str(data.get("effective_date_or_version")),
        rate=float(data["rate"]),
        source=str(data.get("source") or ""),
        source_class=POLICY,
        applicability_established=True,
        applicability_conditions=tuple(data.get("applicability_conditions") or ()),
        public_supporting_only=False,
        note="Account-applicable verified schedule accepted.",
    )


def accept_account_applicable_schedule(schedule: CommissionSchedule | dict[str, Any]) -> CommissionSchedule:
    """27.19 gate: VERIFIED only with complete account/product applicability."""
    data = schedule.to_dict() if isinstance(schedule, CommissionSchedule) else dict(schedule)
    if data.get("public_supporting_only") or generic_public_schedule_is_account_specific(data):
        raise CommissionPolicyError(
            "GENERIC_PUBLIC_NOT_ACCOUNT_SPECIFIC",
            "Public/generic commission documentation is supporting evidence only "
            "and is not an account-specific verified schedule.",
        )
    missing = missing_account_applicability_fields(data)
    if missing:
        raise CommissionPolicyError(
            "APPLICABILITY_REQUIRED",
            "Account-applicable verified schedule rejected; missing: " + ", ".join(missing),
        )
    return accept_verified_schedule(data)


def synthesize_zero_from_observed(values: Iterable[float]) -> float:
    raise CommissionPolicyError(
        "ZERO_FROM_OBSERVED_FORBIDDEN",
        f"Refusing to treat {len(list(values))} observed zero commission value(s) "
        "as a verified zero schedule.",
    )


def enable_zero_commission_from_observed_zeros(values: Iterable[float]) -> None:
    raise CommissionPolicyError(
        "ZERO_ASSUMPTION_FORBIDDEN",
        "Zero-commission assumption is forbidden from observed zeros alone "
        f"(n={len(list(values))}).",
    )


def classify_commission_policy(
    *,
    commission_status: str,
    observed_values: Iterable[float] | None = None,
    schedule: CommissionSchedule | dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = str(commission_status).upper()
    observed = classify_observed_commissions(list(observed_values or []))
    applicable = verified_schedule_requires_applicability(schedule) if schedule is not None else False
    accepted = False
    if schedule is not None and applicable:
        try:
            accept_verified_schedule(schedule)
            accepted = True
        except CommissionPolicyError:
            accepted = False
    return {
        "policy": POLICY,
        "configured_status": status,
        "is_verified_schedule": status == POLICY and accepted,
        "observed_classification": observed.status,
        "observed_zero_equals_verified_schedule": False,
        "generic_public_equals_account_specific": False,
        "applicability_established": applicable,
        "schedule_accepted_for_validation": accepted,
        "cost_adjusted_allowed": False if not accepted else None,
    }


def cost_completeness_from_unknown_commission() -> CostCompleteness:
    cfg = BacktestConfig(
        spread_mode="PROXY",
        commission_status=UNKNOWN,
        swap_status="ZERO",
        slippage_status="MODELED_PROXY",
    )
    return assess_cost_completeness(build_backtest_cost_model(cfg, spread_mode="PROXY"))


def cost_completeness_from_observed_zero_status() -> CostCompleteness:
    cfg = BacktestConfig(
        spread_mode="PROXY",
        commission_status=OBSERVED_ZERO_NOT_PROVEN,
        swap_status="ZERO",
        slippage_status="MODELED_PROXY",
    )
    return assess_cost_completeness(build_backtest_cost_model(cfg, spread_mode="PROXY"))


def cost_completeness_from_verified_schedule_gate_only() -> CostCompleteness:
    """Selecting the policy without an applicable schedule cannot make costs COMPLETE."""
    cfg = BacktestConfig(
        spread_mode="PROXY",
        commission_status=POLICY,
        swap_status="ZERO",
        slippage_status="MODELED_PROXY",
    )
    return assess_cost_completeness(build_backtest_cost_model(cfg, spread_mode="PROXY"))


def dataset_completeness_from_unknown_commission() -> str:
    return compute_dataset_cost_status(
        spread_mode="DATASET",
        commission_status=UNKNOWN,
        swap_status="OBSERVED",
        slippage_status="OBSERVED",
    )["cost_completeness"]


def dataset_completeness_from_observed_zero() -> str:
    return compute_dataset_cost_status(
        spread_mode="DATASET",
        commission_status=OBSERVED_ZERO_NOT_PROVEN,
        swap_status="OBSERVED",
        slippage_status="OBSERVED",
    )["cost_completeness"]


def cost_adjusted_blocked_when_commission_unknown() -> bool:
    result = BacktestResult(
        config=BacktestConfig(commission_status=UNKNOWN),
        initial_balance=1000.0,
        final_balance=1000.0,
        trades=[],
        equity_curve=[{"equity": 1000.0}],
    )
    metrics = compute_metrics(result, cost_completeness=cost_completeness_from_unknown_commission())
    return not bool(metrics.get("cost_adjusted_metrics"))
