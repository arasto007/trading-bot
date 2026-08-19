"""Hybrid decision schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any


class RuleDirection(IntEnum):
    BUY = 1
    SELL = -1
    NONE = 0


DECISION_BUY = "BUY"
DECISION_SELL = "SELL"
DECISION_WAIT = "WAIT"
DECISION_REJECT = "REJECT"

VALID_DECISIONS = frozenset({DECISION_BUY, DECISION_SELL, DECISION_WAIT, DECISION_REJECT})


@dataclass
class RuleSignal:
    direction: int
    strength: float
    source: str = "rule_engine"

    @property
    def label(self) -> str:
        if self.direction > 0:
            return DECISION_BUY
        if self.direction < 0:
            return DECISION_SELL
        return "WAIT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": int(self.direction),
            "strength": round(float(self.strength), 4),
            "source": self.source,
            "label": self.label,
        }


@dataclass
class MLSignal:
    prediction: int
    probability: float
    direction: str
    confidence: str
    accepted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HybridDecision:
    timestamp: str
    symbol: str
    timeframe: str
    rule_signal: str
    ml_prediction: int
    ml_probability: float
    ml_direction: str
    agreement_score: float
    final_score: float
    decision: str
    confidence: str
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rule_output: dict[str, Any] = field(default_factory=dict)
    ml_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HybridDecision":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
