"""Confidence calibration — predicted vs actual success rates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord


@dataclass
class ConfidenceBandReport:
    band: str
    expected_success_rate: float
    actual_success_rate: float
    samples: int
    overestimation: bool
    delta: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationReport:
    bands: list[ConfidenceBandReport] = field(default_factory=list)
    confidence_overestimation: bool = False
    status: str = "PASS"
    overestimation_threshold: float = 0.10

    def to_dict(self) -> dict[str, Any]:
        return {
            "bands": [b.to_dict() for b in self.bands],
            "confidence_overestimation": self.confidence_overestimation,
            "status": self.status,
            "overestimation_threshold": self.overestimation_threshold,
        }


@dataclass
class ConfidenceCalibrator:
    """Compare predicted confidence bands to realized shadow outcomes."""

    expected_rates: dict[str, float] = field(
        default_factory=lambda: {"HIGH": 0.80, "MEDIUM": 0.65, "LOW": 0.55}
    )
    overestimation_threshold: float = 0.10

    def calibrate(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> CalibrationReport:
        buckets: dict[str, list[int]] = {k: [] for k in self.expected_rates}
        for d in decisions:
            if d.decision_id not in outcomes:
                continue
            band = d.confidence.upper()
            if band not in buckets:
                continue
            o = outcomes[d.decision_id]
            if o.label not in (0, 1):
                continue
            success = 1 if d.ml_prediction == o.label else 0
            buckets[band].append(success)

        bands: list[ConfidenceBandReport] = []
        any_over = False
        for band, expected in self.expected_rates.items():
            samples = buckets.get(band, [])
            actual = sum(samples) / len(samples) if samples else 0.0
            delta = expected - actual
            over = delta > self.overestimation_threshold and len(samples) > 0
            any_over = any_over or over
            bands.append(
                ConfidenceBandReport(
                    band=band,
                    expected_success_rate=round(expected, 4),
                    actual_success_rate=round(actual, 4),
                    samples=len(samples),
                    overestimation=over,
                    delta=round(delta, 4),
                )
            )

        return CalibrationReport(
            bands=bands,
            confidence_overestimation=any_over,
            status="FAIL" if any_over else "PASS",
            overestimation_threshold=self.overestimation_threshold,
        )
