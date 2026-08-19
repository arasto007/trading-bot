"""Decision policy — accept/reject ML suggestions (no trading action)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from tradingbot.ml.decision.confidence import ConfidenceConfig, confidence_from_probability
from tradingbot.ml.decision.schema import MLDecision


@dataclass
class PolicyResult:
    accepted: bool
    reason: str


@dataclass
class DecisionPolicy:
    """Rule layer over model output — shadow mode only."""

    min_confidence: str = "LOW"
    reject_low_confidence: bool = True
    max_stale_minutes: float = 120.0
    require_all_features: bool = True

    _confidence_rank: dict[str, int] | None = None

    def __post_init__(self) -> None:
        self._confidence_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

    def evaluate(
        self,
        decision: MLDecision,
        *,
        feature_row: dict[str, Any] | pd.Series | None = None,
        required_features: list[str] | None = None,
        model_valid: bool = True,
    ) -> PolicyResult:
        if not model_valid:
            return PolicyResult(False, "invalid model")

        if required_features and feature_row is not None:
            missing = self._missing_features(feature_row, required_features)
            if missing:
                return PolicyResult(False, f"missing features: {', '.join(missing[:5])}")

        if self._is_stale(decision.timestamp):
            return PolicyResult(False, "stale data")

        if decision.probability < decision.threshold_used:
            return PolicyResult(False, "probability below optimized threshold")

        if decision.prediction != 1:
            return PolicyResult(False, "model predicts SL-first (class 0)")

        if self.reject_low_confidence:
            rank = self._confidence_rank or {}
            if rank.get(decision.confidence, 0) < rank.get(self.min_confidence, 1):
                return PolicyResult(False, "low confidence")

        return PolicyResult(True, "probability above optimized threshold")

    def _missing_features(
        self,
        row: dict[str, Any] | pd.Series,
        required: list[str],
    ) -> list[str]:
        if self.require_all_features is False:
            return []
        data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        missing: list[str] = []
        for name in required:
            if name not in data or pd.isna(data[name]):
                missing.append(name)
        return missing

    def _is_stale(self, timestamp: str) -> bool:
        if not timestamp or self.max_stale_minutes <= 0:
            return False
        try:
            ts = pd.to_datetime(timestamp, utc=True)
        except (TypeError, ValueError):
            return True
        age = datetime.now(timezone.utc) - ts.to_pydatetime()
        return age.total_seconds() > self.max_stale_minutes * 60.0
