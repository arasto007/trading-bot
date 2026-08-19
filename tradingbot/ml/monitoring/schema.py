"""Monitoring schema — snapshots, states, alerts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PerformanceState(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class MonitoringSnapshot:
    timestamp: str
    symbol: str
    timeframe: str
    model_name: str
    model_version: str
    sample_count: int
    expected_R: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    prediction_accuracy: float
    calibration_error: float
    hybrid_vs_rule_delta: float
    feature_drift_score: float
    performance_state: str = PerformanceState.HEALTHY.value
    window: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Alert:
    timestamp: str
    type: str
    severity: str
    message: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WindowMetrics:
    window: int
    expected_R: float
    win_rate: float
    max_drawdown: float
    prediction_accuracy: float
    calibration_error: float
    samples: int
    state: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DegradationReport:
    baseline_R: float
    current_R: float
    drop_percentage: float
    status: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
