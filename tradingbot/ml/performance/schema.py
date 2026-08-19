"""Performance measurement schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PerformanceMetric:
    component: str
    latency_ms: float
    memory_mb: float
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    operation: str
    dataset_size: int
    latency_ms: float
    memory_mb: float
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceProfile:
    system: str = "OK"
    average_prediction_ms: float = 0.0
    feature_build_ms: float = 0.0
    orchestrator_ms: float = 0.0
    hybrid_decision_ms: float = 0.0
    monitoring_ms: float = 0.0
    logging_ms: float = 0.0
    memory_usage_mb: float = 0.0
    metrics: list[PerformanceMetric] = field(default_factory=list)
    benchmarks: list[BenchmarkResult] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "average_prediction_ms": round(self.average_prediction_ms, 2),
            "feature_build_ms": round(self.feature_build_ms, 2),
            "orchestrator_ms": round(self.orchestrator_ms, 2),
            "hybrid_decision_ms": round(self.hybrid_decision_ms, 2),
            "monitoring_ms": round(self.monitoring_ms, 2),
            "logging_ms": round(self.logging_ms, 2),
            "memory_usage_mb": round(self.memory_usage_mb, 2),
            "metrics": [m.to_dict() for m in self.metrics],
            "benchmarks": [b.to_dict() for b in self.benchmarks],
            "recommendations": self.recommendations,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
