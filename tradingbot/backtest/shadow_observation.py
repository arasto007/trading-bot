"""Phase 53 shadow-trading specification — not activated.

Never places orders. Activation is explicitly blocked.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SHADOW_RECORD_FIELDS = (
    "SIGNAL_TIMESTAMP",
    "SYMBOL",
    "TIMEFRAME",
    "SIGNAL",
    "ENTRY_REFERENCE",
    "SL",
    "TP",
    "RISK",
    "SPREAD_AT_SIGNAL",
    "EXPECTED_FILL",
    "HYPOTHETICAL_FILL",
    "ACTUAL_MARKET_PRICE_IF_OBSERVABLE",
    "SLIPPAGE",
    "SIGNAL_LATENCY",
    "EVENT_ID",
    "MODEL_VERSION",
    "CONFIG_VERSION",
    "DATA_VERSION",
    "OUTCOME",
)

COMPARISON_METRICS = (
    "signal_agreement",
    "entry_deviation",
    "sl_tp_deviation",
    "spread_deviation",
    "slippage_deviation",
    "expectancy_drift",
    "wr_drift",
    "pf_drift",
    "event_level_drift",
    "regime_drift",
    "execution_drift",
)

PROCESS_STEPS = (
    "signal_generation",
    "hypothetical_order_creation",
    "hypothetical_fill_model",
    "spread_capture",
    "slippage_measurement",
    "latency_measurement",
    "outcome_tracking",
    "event_grouping",
    "comparison_with_backtest",
    "drift_detection",
    "alert_conditions",
    "stop_conditions",
)


class ShadowActivationBlocked(RuntimeError):
    """Shadow framework must not be turned on in Phase 53."""


class ShadowOrderForbidden(RuntimeError):
    """Shadow mode must never place an order."""


@dataclass(frozen=True)
class ShadowObservation:
    SIGNAL_TIMESTAMP: str | None = None
    SYMBOL: str = ""
    TIMEFRAME: str = "5m"
    SIGNAL: str = ""
    ENTRY_REFERENCE: float | None = None
    SL: float | None = None
    TP: float | None = None
    RISK: float | None = None
    SPREAD_AT_SIGNAL: float | None = None
    EXPECTED_FILL: float | None = None
    HYPOTHETICAL_FILL: float | None = None
    ACTUAL_MARKET_PRICE_IF_OBSERVABLE: float | None = None
    SLIPPAGE: float | None = None
    SIGNAL_LATENCY: float | None = None
    EVENT_ID: str | None = None
    MODEL_VERSION: str = "frozen_phase40"
    CONFIG_VERSION: str = "unchanged"
    DATA_VERSION: str = "XAUUSD_i_5m_phase38"
    OUTCOME: str = "NOT_TRADED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_shadow_acceptance(
    *,
    commission_verified: bool,
    executable_completed: bool,
    execution_parity: str,
    broker_parity: str,
    production_readiness: str,
    robustness_verdict: str,
) -> dict[str, Any]:
    failed: list[str] = []
    if not commission_verified:
        failed.append("commission not VERIFIED")
    if not executable_completed:
        failed.append("executable evaluation not completed")
    if execution_parity == "FAIL":
        failed.append("EXECUTION_PARITY=FAIL")
    if broker_parity == "FAIL":
        failed.append("BROKER_PARITY=FAIL")
    if production_readiness != "READY":
        failed.append(f"PRODUCTION_READINESS={production_readiness}")
    if robustness_verdict == "FRAGILE":
        failed.append("robustness FRAGILE")
    status = "PASSED" if not failed else "BLOCKED"
    return {
        "ACCEPTANCE_GATE": status,
        "SHADOW_ACTIVE": False,
        "ORDERS_PLACED": 0,
        "failed": failed,
        "reason": "specified_not_activated" if status == "PASSED" else failed[0],
    }


class ShadowFramework:
    """Specified, inert. Cannot send orders or start live observation."""

    ACTIVE = False

    def activate(self) -> None:
        raise ShadowActivationBlocked(
            "Phase 53 specifies the shadow framework and does not activate it"
        )

    def place_order(self, *_args: Any, **_kwargs: Any) -> None:
        raise ShadowOrderForbidden("shadow mode must never place an order")

    def hypothetical_fill(self, observation: ShadowObservation) -> dict[str, Any]:
        payload = observation.to_dict()
        payload["OUTCOME"] = "HYPOTHETICAL_ONLY"
        payload["order_sent"] = False
        return payload
