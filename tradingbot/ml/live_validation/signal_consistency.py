"""Phase 15D — deterministic signal consistency checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _fingerprint(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class ConsistencyCheck:
    timestamp: str
    decision_fp: str
    signal_fp: str
    confidence: float
    risk: float
    quality: float
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "decision_fp": self.decision_fp,
            "signal_fp": self.signal_fp,
            "confidence": self.confidence,
            "risk": self.risk,
            "quality": self.quality,
            "direction": self.direction,
        }


@dataclass
class SignalConsistencyValidator:
    checks: list[ConsistencyCheck] = field(default_factory=list)
    replay_mismatches: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, timestamp: str, unified: Any, trading_signal: Any | None) -> ConsistencyCheck:
        u_dict = unified.to_dict() if hasattr(unified, "to_dict") else {}
        sig_meta = dict(getattr(trading_signal, "metadata", None) or {})
        check = ConsistencyCheck(
            timestamp=timestamp,
            decision_fp=_fingerprint({
                "direction": u_dict.get("direction"),
                "confidence": u_dict.get("confidence"),
                "engine": u_dict.get("engine"),
            }),
            signal_fp=_fingerprint({
                "direction": getattr(getattr(trading_signal, "direction", None), "name", None),
                "confidence": getattr(trading_signal, "confidence", None),
            }) if trading_signal else "",
            confidence=float(u_dict.get("confidence", 0.0)),
            risk=float(u_dict.get("risk", 0.0)),
            quality=float(u_dict.get("quality", 0.0)),
            direction=str(u_dict.get("direction", "HOLD")),
        )
        self.checks.append(check)
        return check

    def verify_replay(self, first: ConsistencyCheck, second: ConsistencyCheck) -> bool:
        match = (
            first.decision_fp == second.decision_fp
            and first.signal_fp == second.signal_fp
            and first.confidence == second.confidence
            and first.risk == second.risk
            and first.quality == second.quality
            and first.direction == second.direction
        )
        if not match:
            self.replay_mismatches.append({
                "timestamp": first.timestamp,
                "first": first.to_dict(),
                "second": second.to_dict(),
            })
        return match

    def is_deterministic(self) -> bool:
        return len(self.replay_mismatches) == 0

    def summary(self) -> dict[str, Any]:
        return {
            "checks": len(self.checks),
            "replay_mismatches": len(self.replay_mismatches),
            "deterministic": self.is_deterministic(),
        }
