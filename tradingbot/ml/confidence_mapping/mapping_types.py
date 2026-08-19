"""Phase 15H — confidence scale mapping types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MappingAnchor:
    frozen: float
    research: float
    source: str = "empirical"


@dataclass
class MappingCurve:
    """Monotone frozen → research confidence knots."""

    anchors: list[MappingAnchor]
    frozen_ceiling: float
    research_ceiling: float
    method: str = "pchip"

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "frozen_ceiling": round(self.frozen_ceiling, 6),
            "research_ceiling": round(self.research_ceiling, 6),
            "anchors": [
                {"frozen": round(a.frozen, 6), "research": round(a.research, 6), "source": a.source}
                for a in self.anchors
            ],
        }


@dataclass
class MappingResult:
    frozen_confidence: float
    mapped_confidence: float
    curve_segment: str = ""

    def to_dict(self) -> dict[str, float | str]:
        return {
            "frozen_confidence": round(self.frozen_confidence, 6),
            "mapped_confidence": round(self.mapped_confidence, 6),
            "curve_segment": self.curve_segment,
        }


@dataclass
class MappingTrace:
    frozen: float
    mapped: float
    stage: str = "pre_risk"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frozen_confidence": round(self.frozen, 6),
            "mapped_confidence": round(self.mapped, 6),
            "stage": self.stage,
            "metadata": self.metadata,
        }
