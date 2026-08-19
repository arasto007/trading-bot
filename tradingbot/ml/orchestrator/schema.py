"""Orchestrator schema — final shadow decision types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_REJECT, DECISION_SELL, DECISION_WAIT


class ConfidenceLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class StrategyMode(str, Enum):
    RULE_ONLY = "RULE_ONLY"
    ML_ONLY = "ML_ONLY"
    HYBRID = "HYBRID"
    ENSEMBLE = "ENSEMBLE"
    SAFE_MODE = "SAFE_MODE"


class RiskState(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


FINAL_ACTIONS = frozenset({DECISION_BUY, DECISION_SELL, DECISION_WAIT, DECISION_REJECT})


@dataclass
class OrchestratorConfig:
    """Tunable orchestrator thresholds — shadow only."""

    ml_weight_min: float = 0.3
    ml_weight_max: float = 0.8
    rule_weight_min: float = 0.2
    rule_weight_max: float = 0.6
    hybrid_weight_base: float = 0.35
    ab_bias: float = 0.05
    buy_threshold: float = 0.35
    sell_threshold: float = -0.35
    drawdown_caution_r: float = 10.0
    drawdown_block_r: float = 25.0
    loss_streak_caution: int = 3
    loss_streak_restrict: int = 5
    drift_warning: float = 0.15
    drift_block: float = 0.30
    spread_block: float = 0.75
    min_score: float = 0.55

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestratorSnapshot:
    """Point-in-time inputs for final decision — no future data."""

    timestamp: str
    symbol: str
    timeframe: str
    rule_signal: str = DECISION_WAIT
    ml_prediction: int = 0
    ml_probability: float = 0.0
    hybrid_decision: str = DECISION_WAIT
    hybrid_score: float = 0.0
    final_score: float = 0.0
    direction: int = 0
    session: str = "unknown"
    regime: str = "unknown"
    features_snapshot: dict[str, float] = field(default_factory=dict)
    ab_winner: str = "NO_DIFFERENCE"
    performance_state: str = "HEALTHY"
    calibration_error: float = 0.0
    feature_drift_score: float = 0.0
    max_drawdown_r: float = 0.0
    loss_streak: int = 0
    paper_expectancy_r: float = 0.0
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrchestratorSnapshot":
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields if k in data})


@dataclass
class SourceContributions:
    ml_signal: float = 0.0
    rule_signal: float = 0.0
    hybrid_score: float = 0.0
    ab_bias: float = 0.0
    performance_adjustment: float = 0.0
    ml_weight: float = 0.0
    rule_weight: float = 0.0
    hybrid_weight: float = 0.0
    raw_score: float = 0.0
    adjusted_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FinalDecision:
    timestamp: str
    symbol: str
    timeframe: str
    action: str
    confidence: str
    active_strategy: str
    reasoning: list[str] = field(default_factory=list)
    risk_state: str = RiskState.NORMAL.value
    source_contributions: SourceContributions = field(default_factory=SourceContributions)
    ensemble_score: float = 0.0
    regime: str = "unknown"
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_contributions"] = self.source_contributions.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FinalDecision":
        contrib = data.get("source_contributions", {})
        return cls(
            timestamp=data["timestamp"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            action=data["action"],
            confidence=data["confidence"],
            active_strategy=data["active_strategy"],
            reasoning=list(data.get("reasoning", [])),
            risk_state=data.get("risk_state", RiskState.NORMAL.value),
            source_contributions=SourceContributions(**contrib) if isinstance(contrib, dict) else contrib,
            ensemble_score=float(data.get("ensemble_score", 0.0)),
            regime=data.get("regime", "unknown"),
            trace=dict(data.get("trace", {})),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
