"""Optimization schema — shadow policy tuning results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PolicyConfig:
    threshold: float = 0.50
    ml_weight: float = 0.60
    rule_weight: float = 0.40
    min_score: float = 0.60
    disabled_sessions: list[str] = field(default_factory=list)
    disabled_regimes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyConfig":
        return cls(
            threshold=float(data.get("threshold", 0.5)),
            ml_weight=float(data.get("ml_weight", 0.6)),
            rule_weight=float(data.get("rule_weight", 0.4)),
            min_score=float(data.get("min_score", 0.6)),
            disabled_sessions=list(data.get("disabled_sessions", [])),
            disabled_regimes=list(data.get("disabled_regimes", [])),
        )

    def normalized(self) -> "PolicyConfig":
        total = self.ml_weight + self.rule_weight
        if total > 0 and abs(total - 1.0) > 1e-6:
            return PolicyConfig(
                threshold=self.threshold,
                ml_weight=self.ml_weight / total,
                rule_weight=self.rule_weight / total,
                min_score=self.min_score,
                disabled_sessions=list(self.disabled_sessions),
                disabled_regimes=list(self.disabled_regimes),
            )
        return self


@dataclass
class OptimizationResult:
    timestamp: str
    symbol: str
    timeframe: str
    current_config: PolicyConfig
    recommended_config: PolicyConfig
    expected_R_before: float
    expected_R_after: float
    confidence_change: float
    sample_size: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "current_config": self.current_config.to_dict(),
            "recommended_config": self.recommended_config.to_dict(),
            "expected_R_before": self.expected_R_before,
            "expected_R_after": self.expected_R_after,
            "confidence_change": self.confidence_change,
            "sample_size": self.sample_size,
            "warnings": self.warnings,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
