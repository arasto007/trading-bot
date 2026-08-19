"""Live gate schema — permission flags only, no execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class LiveGateState(str, Enum):
    BLOCKED = "BLOCKED"
    SHADOW_ONLY = "SHADOW_ONLY"
    CONDITIONAL_SHADOW = "CONDITIONAL_SHADOW"
    READY_FOR_MANUAL = "READY_FOR_MANUAL"


class AllowedMode(str, Enum):
    SHADOW_ONLY = "shadow_only"
    BLOCKED = "blocked"


class RiskFlagLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class LivePermission:
    state: str
    readiness_score: float
    allowed_mode: str
    risk_flag: str
    reason: str
    symbol: str = ""
    timeframe: str = ""
    readiness_status: str = ""
    auto_trading_allowed: bool = False
    manual_activation_allowed: bool = False
    shadow_routing_allowed: bool = True
    timestamp: str = ""
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LivePermission":
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields if k in data})


@dataclass
class LiveGateReport:
    timestamp: str
    symbol: str
    timeframe: str
    permission: LivePermission
    readiness_source: str = "phase_6_4"
    execution_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "permission": self.permission.to_dict(),
            "readiness_source": self.readiness_source,
            "execution_enabled": self.execution_enabled,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
