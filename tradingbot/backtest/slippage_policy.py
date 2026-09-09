"""Operator slippage policy: MODELED, implemented as MODELED_PROXY.

MODELED slippage is not REALIZED slippage.
MT5 deviation is an execution parameter, not a fill distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from tradingbot.adapters.mt5_execution import _DEVIATION
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
from tradingbot.backtest.operator_evidence import (
    FieldAvailability,
    SlippageEvidenceClass,
    parse_closed_deal,
)
from tradingbot.domain.session_logic import session_cost_multiplier

POLICY = "MODELED"
IMPLEMENTATION_LABEL = "MODELED_PROXY"

# Inherited from Phase 27.5 / 27.7 gate language (n>=10). Not a newly fitted parameter.
STATISTICAL_MIN_SAMPLES_ASSUMPTION = 10

# Existing BacktestConfig default. Not measured from fills.
BASE_SLIPPAGE_PIPS_ASSUMPTION = 0.8

# Existing session_logic.session_cost_multiplier. Not fitted from fills.
SESSION_MULTIPLIER_ASSUMPTIONS = {
    "ny_overlap_12_17": 1.0,
    "london_or_late_ny_8_12_or_17_21": 1.25,
    "asian_0_7": 1.6,
    "other": 1.4,
}


class SlippagePolicyError(Exception):
    """Slippage policy violation — fail closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ModeledSlippageContract:
    policy: str
    status: str
    model_type: str
    units: str
    direction_handling: str
    parameters: dict[str, Any]
    assumptions: list[str]
    source_evidence_basis: str
    limitations: list[str]
    provenance: str
    realized_sample_count: int
    statistically_sufficient_realized: bool
    mt5_deviation_points: int
    mt5_deviation_is_realized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "status": self.status,
            "model_type": self.model_type,
            "units": self.units,
            "direction_handling": self.direction_handling,
            "parameters": self.parameters,
            "assumptions": list(self.assumptions),
            "source_evidence_basis": self.source_evidence_basis,
            "limitations": list(self.limitations),
            "provenance": self.provenance,
            "realized_sample_count": self.realized_sample_count,
            "statistically_sufficient_realized": self.statistically_sufficient_realized,
            "mt5_deviation_points": self.mt5_deviation_points,
            "mt5_deviation_is_realized": self.mt5_deviation_is_realized,
        }


def modeled_is_not_realized() -> bool:
    return POLICY != "REALIZED" and IMPLEMENTATION_LABEL != "REALIZED"


def mt5_deviation_is_realized_slippage() -> bool:
    return False


def realized_samples_from_deals(deals: Iterable[dict[str, Any]]) -> list[float]:
    """Count only requested_price vs actual_fill. entry_price is not requested."""
    samples: list[float] = []
    for raw in deals:
        rec = parse_closed_deal({"closed_deal": raw}, source="phase27_14")
        if rec is None:
            continue
        if rec.slippage_class != SlippageEvidenceClass.REALIZED.value:
            continue
        if rec.realized_slippage and rec.realized_slippage.availability == FieldAvailability.OBSERVED.value:
            try:
                samples.append(float(rec.realized_slippage.value))
            except (TypeError, ValueError):
                pass
    return samples


def statistically_sufficient_realized(sample_count: int) -> bool:
    """Thin requested-vs-fill sets are not a realized distribution."""
    return sample_count >= STATISTICAL_MIN_SAMPLES_ASSUMPTION


def inflate_requested_vs_fill_to_realized_distribution(sample_count: int) -> list[float]:
    raise SlippagePolicyError(
        "REALIZED_INFLATION_FORBIDDEN",
        f"Refusing to treat {sample_count} requested-vs-fill sample(s) as a realized distribution "
        f"(assumption threshold={STATISTICAL_MIN_SAMPLES_ASSUMPTION}).",
    )


def modeled_cannot_silently_become_zero() -> bool:
    model = build_backtest_cost_model(BacktestConfig(slippage_status=IMPLEMENTATION_LABEL, slippage_pips=0.0))
    return (
        model.slippage.availability == CostAvailability.UNKNOWN
        and model.slippage.value is None
    )


def cost_completeness_from_modeled_slippage_only() -> CostCompleteness:
    """A modeled parameter alone cannot make the cost contract COMPLETE."""
    cfg = BacktestConfig(
        spread_mode="PROXY",
        commission_status="ZERO",
        swap_status="ZERO",
        slippage_status=IMPLEMENTATION_LABEL,
        slippage_pips=BASE_SLIPPAGE_PIPS_ASSUMPTION,
    )
    return assess_cost_completeness(build_backtest_cost_model(cfg, spread_mode="PROXY"))


def dataset_completeness_from_modeled_slippage() -> str:
    return compute_dataset_cost_status(
        spread_mode="DATASET",
        commission_status="OBSERVED",
        swap_status="OBSERVED",
        slippage_status=IMPLEMENTATION_LABEL,
    )["cost_completeness"]


def cost_adjusted_blocked_when_slippage_modeled_proxy() -> bool:
    result = BacktestResult(
        config=BacktestConfig(slippage_status=IMPLEMENTATION_LABEL),
        initial_balance=1000.0,
        final_balance=1000.0,
        trades=[],
        equity_curve=[{"equity": 1000.0}],
    )
    metrics = compute_metrics(result, cost_completeness=cost_completeness_from_modeled_slippage_only())
    return not bool(metrics.get("cost_adjusted_metrics"))


def classify_slippage(
    *,
    slippage_status: str,
    realized_sample_count: int,
) -> dict[str, Any]:
    status = str(slippage_status).upper()
    sufficient = statistically_sufficient_realized(realized_sample_count)
    if status == "REALIZED" and not sufficient:
        evidence_class = SlippageEvidenceClass.UNKNOWN.value
    elif status in (POLICY, IMPLEMENTATION_LABEL):
        evidence_class = IMPLEMENTATION_LABEL
    elif status == "REALIZED" and sufficient:
        evidence_class = SlippageEvidenceClass.REALIZED.value
    else:
        evidence_class = SlippageEvidenceClass.UNKNOWN.value
    return {
        "policy": POLICY,
        "implementation_label": IMPLEMENTATION_LABEL,
        "configured_status": status,
        "evidence_class": evidence_class,
        "is_modeled": status in (POLICY, IMPLEMENTATION_LABEL),
        "is_realized": status == "REALIZED" and sufficient,
        "modeled_equals_realized": False,
        "realized_sample_count": realized_sample_count,
        "statistically_sufficient_realized": sufficient,
        "mt5_deviation_is_realized": mt5_deviation_is_realized_slippage(),
        "cost_adjusted_allowed": False if evidence_class != SlippageEvidenceClass.REALIZED.value else None,
    }


def build_modeled_slippage_contract(*, realized_sample_count: int) -> ModeledSlippageContract:
    sufficient = statistically_sufficient_realized(realized_sample_count)
    return ModeledSlippageContract(
        policy=POLICY,
        status=IMPLEMENTATION_LABEL,
        model_type="session_hour_variable_proxy",
        units="pips_per_leg",
        direction_handling=(
            "Adverse-to-trader on SimulatedBroker: buy fill worse (price + half-spread + slip); "
            "sell fill worse (price - half-spread - slip). Same proxy applied per exit leg when modeled."
        ),
        parameters={
            "base_slippage_pips": BASE_SLIPPAGE_PIPS_ASSUMPTION,
            "session_multipliers": SESSION_MULTIPLIER_ASSUMPTIONS,
            "example_hour_15_pips": round(
                BASE_SLIPPAGE_PIPS_ASSUMPTION * session_cost_multiplier(15), 2
            ),
        },
        assumptions=[
            f"base_slippage_pips={BASE_SLIPPAGE_PIPS_ASSUMPTION} is the existing BacktestConfig default, not a fill-derived estimate",
            "session_cost_multiplier(hour) from tradingbot.domain.session_logic is an inherited session-cost assumption, not a slippage fit",
            f"statistically sufficient realized distribution requires >= {STATISTICAL_MIN_SAMPLES_ASSUMPTION} requested-vs-fill pairs (inherited Phase 27.5/27.7 language)",
            "entry_price is not requested_price and must not be used to invent a requested-vs-fill pair",
        ],
        source_evidence_basis=(
            "Configured research proxy. Operator deal tape does not provide a sufficient "
            "requested_price vs actual_fill_price history."
        ),
        limitations=[
            "Not a historical execution distribution",
            "Not account-specific realized slippage",
            "MT5 deviation is a request tolerance, not slippage",
            "A configured parameter cannot close the cost-completeness gate",
            "Sparse or missing requested-vs-fill pairs remain UNKNOWN for REALIZED class",
        ],
        provenance="tradingbot/backtest/config.py + tradingbot/domain/session_logic.py + Phase 27.14 contract",
        realized_sample_count=realized_sample_count,
        statistically_sufficient_realized=sufficient,
        mt5_deviation_points=int(_DEVIATION),
        mt5_deviation_is_realized=False,
    )
