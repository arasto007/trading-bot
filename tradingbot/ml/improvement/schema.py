"""Improvement recommendation schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class SuggestionAction(str, Enum):
    ADD = "ADD"
    REMOVE = "REMOVE"
    MODIFY = "MODIFY"


class QueueStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


def new_queue_id() -> str:
    return str(uuid4())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ImprovementOpportunity:
    issue: str
    recommendation: str
    confidence: float
    category: str = "general"
    expected_impact: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureSuggestion:
    feature: str
    action: str
    reason: str
    confidence: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelSuggestion:
    model_name: str
    suggestion_type: str
    recommendation: str
    parameter_ranges: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThresholdSuggestion:
    current_threshold: float
    recommended_threshold: float
    reason: str
    expected_R_impact: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RegimeSuggestion:
    regime: str
    filter_recommendation: str
    reason: str
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentQueueItem:
    id: str
    hypothesis: str
    expected_improvement: str
    priority: int
    required_resources: list[str]
    status: str = QueueStatus.PENDING.value
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentQueueItem":
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields if k in data})
