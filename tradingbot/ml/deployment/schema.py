"""Deployment readiness schema — evaluation only, no execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ReadinessStatus(str, Enum):
    LIVE_READY = "LIVE_READY"
    CONDITIONAL_READY = "CONDITIONAL_READY"
    NOT_READY = "NOT_READY"


class StabilityState(str, Enum):
    STABLE = "STABLE"
    UNSTABLE = "UNSTABLE"
    CRITICAL = "CRITICAL"


@dataclass
class DeploymentPolicyConfig:
    """Safe thresholds — manual override only, no auto deployment."""

    live_ready_threshold: float = 0.80
    conditional_threshold: float = 0.60
    max_drawdown_r: float = 25.0
    max_drawdown_pct: float = 0.25
    max_calibration_error: float = 0.15
    max_drift_score: float = 0.25
    min_win_rate: float = 0.50
    min_ab_samples: int = 100
    min_paper_trades: int = 50
    allow_auto_deployment: bool = False
    manual_override_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReadinessMetrics:
    """Normalized inputs for readiness evaluation."""

    paper_win_rate: float = 0.0
    paper_expectancy_r: float = 0.0
    paper_max_drawdown_r: float = 0.0
    paper_sharpe: float = 0.0
    paper_trade_count: int = 0
    monitoring_health: float = 0.0
    expected_r: float = 0.0
    performance_state: str = "HEALTHY"
    feature_drift_score: float = 0.0
    calibration_error: float = 0.0
    ab_winner: str = "NO_DIFFERENCE"
    ab_confidence: str = "LOW"
    ab_sample_size: int = 0
    ab_improvement: float = 0.0
    degradation_status: str = "HEALTHY"
    degradation_drop_pct: float = 0.0
    shadow_validation_score: float = 0.0
    shadow_stability_score: float = 0.0
    shadow_noise_ratio: float = 0.0
    stability_state: str = StabilityState.STABLE.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoringBreakdown:
    paper_trading_performance: float = 0.0
    monitoring_health: float = 0.0
    feature_stability: float = 0.0
    ab_consistency: float = 0.0
    calibration_quality: float = 0.0
    degradation_component: float = 0.0
    composite_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LiveReadinessReport:
    timestamp: str
    symbol: str
    timeframe: str
    status: str
    score: float
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    recommendation_text: str = ""
    scoring: ScoringBreakdown = field(default_factory=ScoringBreakdown)
    metrics: ReadinessMetrics = field(default_factory=ReadinessMetrics)
    kill_switch_active: bool = False
    block_deployment: bool = False
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scoring"] = self.scoring.to_dict()
        payload["metrics"] = self.metrics.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveReadinessReport":
        scoring = data.get("scoring", {})
        metrics = data.get("metrics", {})
        return cls(
            timestamp=data["timestamp"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            status=data["status"],
            score=float(data["score"]),
            reasons=list(data.get("reasons", [])),
            risk_flags=list(data.get("risk_flags", [])),
            recommendation_text=data.get("recommendation_text", ""),
            scoring=ScoringBreakdown(**scoring) if isinstance(scoring, dict) else scoring,
            metrics=ReadinessMetrics(**metrics) if isinstance(metrics, dict) else metrics,
            kill_switch_active=bool(data.get("kill_switch_active", False)),
            block_deployment=bool(data.get("block_deployment", False)),
            trace=dict(data.get("trace", {})),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
