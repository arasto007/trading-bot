"""Health check schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    WARNING = "WARNING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ComponentHealth:
    name: str
    status: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SystemHealthReport:
    timestamp: str
    symbol: str
    timeframe: str
    overall_status: str
    components: list[ComponentHealth] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "overall_status": self.overall_status,
            "components": [c.to_dict() for c in self.components],
            "warnings": self.warnings,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
