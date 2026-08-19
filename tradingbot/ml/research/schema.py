"""Research intelligence schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class ExperimentStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class HypothesisStatus(str, Enum):
    OPEN = "OPEN"
    TESTING = "TESTING"
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


def new_experiment_id() -> str:
    return str(uuid4())


def new_hypothesis_id() -> str:
    return str(uuid4())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExperimentRecord:
    experiment_id: str
    timestamp: str
    dataset_hash: str
    feature_version: str
    model_name: str
    model_version: str
    parameters: dict[str, Any]
    validation_method: str
    metrics: dict[str, float]
    expected_R: float
    notes: str = ""
    status: str = ExperimentStatus.COMPLETE.value
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    reproducibility: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentRecord":
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields if k in data})


@dataclass
class Hypothesis:
    id: str
    description: str
    target_metric: str
    experiment_ids: list[str] = field(default_factory=list)
    result: str = ""
    confidence: float = 0.0
    status: str = HypothesisStatus.OPEN.value
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hypothesis":
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields if k in data})


@dataclass
class ModelComparisonEntry:
    model_name: str
    roc_auc: float
    pr_auc: float
    expected_R: float
    profit_factor: float
    max_drawdown: float
    stability_score: float
    calibration_error: float
    overall_score: float
    sample_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchRankingEntry:
    rank: int
    name: str
    category: str
    score: float
    expected_R: float
    stability: float
    sample_size: int
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
