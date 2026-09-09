"""Reusable cost evidence schema — Phase 27 broker reality foundation.

Never stores credentials. All fields are evidence-classified, not policy decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SpreadEvidence:
    source: str = ""
    method: str = ""
    sample_count: int | None = None
    timestamp_range: str = ""
    value: float | None = None
    units: str = ""
    evidence_class: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CommissionEvidence:
    source: str = ""
    schedule_or_value: str = ""
    sample_count: int | None = None
    timestamp_range: str = ""
    evidence_class: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SwapEvidence:
    source: str = ""
    long: float | None = None
    short: float | None = None
    rollover_3day: int | None = None
    sample_count: int | None = None
    timestamp_range: str = ""
    evidence_class: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlippageEvidence:
    requested_price: float | None = None
    fill_price: float | None = None
    direction: str = ""
    volume: float | None = None
    timestamp: str = ""
    realized_slippage: float | None = None
    evidence_class: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionEvidence:
    requested_volume: float | None = None
    filled_volume: float | None = None
    partial_fill: bool | None = None
    execution_price: float | None = None
    timestamp: str = ""
    order_deal_relation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CostEvidenceBundle:
    """Aggregate cost evidence for one symbol/environment."""

    logical_symbol: str = ""
    broker_symbol: str = ""
    environment: str = ""
    spread: SpreadEvidence = field(default_factory=SpreadEvidence)
    commission: CommissionEvidence = field(default_factory=CommissionEvidence)
    swap: SwapEvidence = field(default_factory=SwapEvidence)
    slippage: SlippageEvidence = field(default_factory=SlippageEvidence)
    execution: ExecutionEvidence = field(default_factory=ExecutionEvidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_symbol": self.logical_symbol,
            "broker_symbol": self.broker_symbol,
            "environment": self.environment,
            "spread": self.spread.to_dict(),
            "commission": self.commission.to_dict(),
            "swap": self.swap.to_dict(),
            "slippage": self.slippage.to_dict(),
            "execution": self.execution.to_dict(),
        }


def serialize_evidence_deterministic(bundle: CostEvidenceBundle) -> str:
    """Stable JSON serialization for immutability checks."""
    import json

    return json.dumps(bundle.to_dict(), sort_keys=True, separators=(",", ":"))
