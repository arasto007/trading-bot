"""Phase 15D — ML vs legacy decision comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComparisonRecord:
    timestamp: str
    legacy_direction: str | None
    ml_direction: str | None
    agreement: bool
    direction_match: bool
    confidence_diff: float
    risk_diff: float
    quality_diff: float
    legacy_confidence: float = 0.0
    ml_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "legacy_direction": self.legacy_direction,
            "ml_direction": self.ml_direction,
            "agreement": self.agreement,
            "direction_match": self.direction_match,
            "confidence_diff": round(self.confidence_diff, 6),
            "risk_diff": round(self.risk_diff, 6),
            "quality_diff": round(self.quality_diff, 6),
            "legacy_confidence": round(self.legacy_confidence, 6),
            "ml_confidence": round(self.ml_confidence, 6),
        }


@dataclass
class DecisionComparer:
    records: list[ComparisonRecord] = field(default_factory=list)

    def compare(
        self,
        *,
        timestamp: str,
        legacy_signal: Any | None,
        ml_signal: Any | None,
        ml_unified: Any | None = None,
    ) -> ComparisonRecord:
        leg_dir = None
        leg_conf = 0.0
        if legacy_signal is not None:
            leg_dir = getattr(getattr(legacy_signal, "direction", None), "name", None)
            leg_conf = float(getattr(legacy_signal, "confidence", 0.0))

        ml_dir = None
        ml_conf = 0.0
        ml_risk = 0.0
        ml_quality = 0.0
        if ml_unified is not None:
            ml_dir = ml_unified.direction
            ml_conf = float(ml_unified.confidence)
            ml_risk = float(ml_unified.risk)
            ml_quality = float(ml_unified.quality)
        elif ml_signal is not None:
            ml_dir = getattr(getattr(ml_signal, "direction", None), "name", None)
            ml_conf = float(getattr(ml_signal, "confidence", 0.0))
            meta = getattr(ml_signal, "metadata", {}) or {}
            ml_risk = float(meta.get("risk_percent", 0.0))
            ml_quality = float(meta.get("quality", 0.0))

        direction_match = leg_dir == ml_dir
        both_hold = leg_dir in (None, "HOLD") and ml_dir in (None, "HOLD")
        agreement = direction_match or both_hold

        rec = ComparisonRecord(
            timestamp=timestamp,
            legacy_direction=leg_dir,
            ml_direction=ml_dir,
            agreement=agreement,
            direction_match=direction_match,
            confidence_diff=abs(leg_conf - ml_conf),
            risk_diff=ml_risk,
            quality_diff=ml_quality,
            legacy_confidence=leg_conf,
            ml_confidence=ml_conf,
        )
        self.records.append(rec)
        return rec

    def summary(self) -> dict[str, Any]:
        n = len(self.records)
        if not n:
            return {"total": 0, "agreement_rate": 0.0, "direction_match_rate": 0.0}
        agree = sum(1 for r in self.records if r.agreement)
        match = sum(1 for r in self.records if r.direction_match)
        disagree_dir = sum(1 for r in self.records if not r.direction_match and r.legacy_direction not in (None, "HOLD") and r.ml_direction not in (None, "HOLD"))
        return {
            "total": n,
            "agreement": agree,
            "disagreement": n - agree,
            "agreement_rate": round(agree / n, 4),
            "direction_match_rate": round(match / n, 4),
            "different_direction": disagree_dir,
            "mean_confidence_diff": round(sum(r.confidence_diff for r in self.records) / n, 4),
            "mean_risk_diff": round(sum(r.risk_diff for r in self.records) / n, 4),
            "mean_quality_diff": round(sum(r.quality_diff for r in self.records) / n, 4),
        }
