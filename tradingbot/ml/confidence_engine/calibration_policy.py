"""Phase 14.2A — calibration policy constants."""

from __future__ import annotations

from dataclasses import dataclass

MIN_RAW_CONFIDENCE = 0.10
MIN_CALIBRATED_CONFIDENCE = 0.55
MAX_CONFIDENCE = 1.0

# Phase 13.10 / 9.9 validated references (frozen — not optimized here).
PHASE99_VALIDATED_PF = 1.06
TREND_RF_VALIDATED_PF = 1.21
TREND_RF_WF_ROBUSTNESS = 0.83
TREND_RF_MONTE_CARLO = 1.0

RANGE_ENGINE_FACTOR_MIN = 0.8
RANGE_ENGINE_FACTOR_MAX = 1.3
TREND_ENGINE_FACTOR_MIN = 1.0
TREND_ENGINE_FACTOR_MAX = 1.5


@dataclass(frozen=True)
class CalibrationPolicy:
    min_raw_confidence: float = MIN_RAW_CONFIDENCE
    min_calibrated_confidence: float = MIN_CALIBRATED_CONFIDENCE
    max_confidence: float = MAX_CONFIDENCE

    def passes_gate(self, calibrated: float) -> bool:
        return calibrated >= self.min_calibrated_confidence

    def raw_eligible(self, raw: float) -> bool:
        return raw >= self.min_raw_confidence


DEFAULT_CALIBRATION_POLICY = CalibrationPolicy()
