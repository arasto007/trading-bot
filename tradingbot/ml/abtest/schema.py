"""A/B shadow test schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

WINNER_HYBRID = "HYBRID_BETTER"
WINNER_RULE = "RULE_BETTER"
WINNER_TIE = "NO_DIFFERENCE"
STATUS_INSUFFICIENT = "INSUFFICIENT_DATA"
STATUS_COMPLETE = "COMPLETE"


@dataclass
class ABDecisionRecord:
    timestamp: str
    symbol: str
    timeframe: str
    rule_decision: str
    hybrid_decision: str
    rule_score: float
    hybrid_score: float
    rule_outcome: str
    hybrid_outcome: str
    rule_R: float
    hybrid_R: float
    winner: str
    decision_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ABDecisionRecord":
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields if k in data})


@dataclass
class ABTestReport:
    symbol: str
    timeframe: str
    sample_size: int
    status: str
    rule_expected_R: float
    hybrid_expected_R: float
    rule_win_rate: float
    hybrid_win_rate: float
    rule_average_R: float
    hybrid_average_R: float
    rule_drawdown: float
    hybrid_drawdown: float
    rule_trade_frequency: float
    hybrid_trade_frequency: float
    improvement: float
    winner: str
    confidence: str
    margin: float = 0.05
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def outcome_label(r_value: float, took_trade: bool) -> str:
    if not took_trade:
        return "SKIP"
    if r_value > 0:
        return "WIN"
    if r_value < 0:
        return "LOSS"
    return "UNRESOLVED"


def record_winner(rule_r: float, hybrid_r: float, rule_took: bool, hybrid_took: bool) -> str:
    if not rule_took and not hybrid_took:
        return WINNER_TIE
    if rule_took and not hybrid_took:
        return WINNER_RULE if rule_r > 0 else WINNER_TIE
    if hybrid_took and not rule_took:
        return WINNER_HYBRID if hybrid_r > 0 else WINNER_TIE
    if hybrid_r > rule_r:
        return WINNER_HYBRID
    if rule_r > hybrid_r:
        return WINNER_RULE
    return WINNER_TIE
