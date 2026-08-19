"""Phase 14.6 — calibration alternative methods (research-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from tradingbot.ml.confidence_engine.calibration_trace import confidence_band
from tradingbot.ml.confidence_engine.calibrator import ConfidenceCalibrator, clamp
from tradingbot.ml.confidence_engine.calibration_types import CalibratedConfidence, RawConfidence
from tradingbot.ml.research.phase14_6.config import RANGE_ENGINE_ID, TRAIN_SPLIT, TREND_ENGINE_ID


@dataclass
class CalibrationSample:
    raw: RawConfidence
    outcome: int | None = None
    timestamp: str = ""


class CalibrationMethod(Protocol):
    name: str

    def fit(self, samples: list[CalibrationSample]) -> None: ...

    def calibrate(self, raw: RawConfidence) -> CalibratedConfidence: ...


def _to_calibrated(raw: RawConfidence, value: float, *, adjustments: list[str]) -> CalibratedConfidence:
    calibrated = clamp(value)
    adj_factor = calibrated / raw.raw_value if raw.raw_value > 0 else 0.0
    return CalibratedConfidence(
        calibrated_value=round(calibrated, 6),
        adjustment_factor=round(adj_factor, 6),
        confidence_band=confidence_band(calibrated),
        explanation=[f"research calibration: {adjustments[-1] if adjustments else 'mapped'}"],
        trace=[f"Raw {raw.raw_value:.4f}", f"Calibrated {calibrated:.4f}"],
        adjustments=adjustments,
        raw_value=raw.raw_value,
        engine=raw.engine,
        regime=raw.regime,
    )


class Phase14_2ACalibration:
    """Benchmark: current production Phase 14.2A calibrator."""

    name = "phase14_2a"

    def __init__(self) -> None:
        self._calibrator = ConfidenceCalibrator()

    def fit(self, samples: list[CalibrationSample]) -> None:
        return None

    def calibrate(self, raw: RawConfidence) -> CalibratedConfidence:
        return self._calibrator.calibrate(raw)


class PercentileCalibration:
    """Percentile rank mapping per engine."""

    name = "percentile"

    def __init__(self) -> None:
        self._engine_values: dict[str, list[float]] = {}

    def fit(self, samples: list[CalibrationSample]) -> None:
        self._engine_values = {RANGE_ENGINE_ID: [], TREND_ENGINE_ID: []}
        for s in samples:
            eng = str(s.raw.engine or "")
            if eng in self._engine_values:
                self._engine_values[eng].append(float(s.raw.raw_value))

    def _percentile_rank(self, engine: str, value: float) -> float:
        vals = sorted(self._engine_values.get(engine, []))
        if not vals:
            return 0.5
        rank = sum(1 for v in vals if v <= value) / len(vals)
        return rank

    def _map_rank(self, rank: float) -> float:
        if rank >= 0.90:
            return 0.90
        if rank >= 0.75:
            return 0.75
        if rank >= 0.40:
            return 0.55
        return 0.30

    def calibrate(self, raw: RawConfidence) -> CalibratedConfidence:
        engine = str(raw.engine or RANGE_ENGINE_ID)
        rank = self._percentile_rank(engine, float(raw.raw_value))
        mapped = self._map_rank(rank)
        return _to_calibrated(raw, mapped, adjustments=[f"percentile rank {rank:.2f} → {mapped:.2f}"])


class ProbabilityCalibration:
    """Platt scaling or isotonic regression per engine."""

    name: str

    def __init__(self, method: str = "platt") -> None:
        self.name = method
        self._models: dict[str, Any] = {}

    def fit(self, samples: list[CalibrationSample]) -> None:
        by_engine: dict[str, list[tuple[float, int]]] = {RANGE_ENGINE_ID: [], TREND_ENGINE_ID: []}
        for s in samples:
            if s.outcome is None:
                continue
            eng = str(s.raw.engine or "")
            if eng in by_engine:
                by_engine[eng].append((float(s.raw.raw_value), int(s.outcome)))

        self._models = {}
        for eng, pairs in by_engine.items():
            if len(pairs) < 20:
                continue
            pairs = sorted(pairs, key=lambda p: p[0])
            split = max(10, int(len(pairs) * TRAIN_SPLIT))
            train = pairs[:split]
            x_train = np.array([p[0] for p in train], dtype=float).reshape(-1, 1)
            y_train = np.array([p[1] for p in train], dtype=int)
            if self.name == "isotonic":
                model = IsotonicRegression(out_of_bounds="clip")
                model.fit(x_train.ravel(), y_train)
            else:
                model = LogisticRegression(max_iter=500)
                model.fit(x_train, y_train)
            self._models[eng] = model

    def calibrate(self, raw: RawConfidence) -> CalibratedConfidence:
        engine = str(raw.engine or RANGE_ENGINE_ID)
        model = self._models.get(engine)
        if model is None:
            return _to_calibrated(raw, raw.raw_value, adjustments=["probability fallback raw"])
        x = np.array([[float(raw.raw_value)]], dtype=float)
        if self.name == "isotonic":
            prob = float(model.predict(x.ravel())[0])
        else:
            prob = float(model.predict_proba(x)[0, 1])
        return _to_calibrated(raw, prob, adjustments=[f"{self.name} probability {prob:.4f}"])


@dataclass
class EngineSpecificCalibration:
    """Separate calibration policy per engine (RANGE=phase9_9, TREND=trend_rf_v40)."""

    methods: dict[str, CalibrationMethod] = field(default_factory=dict)
    fallback: CalibrationMethod | None = None

    def fit(self, samples: list[CalibrationSample]) -> None:
        range_samples = [s for s in samples if s.raw.engine == RANGE_ENGINE_ID]
        trend_samples = [s for s in samples if s.raw.engine == TREND_ENGINE_ID]
        if RANGE_ENGINE_ID in self.methods:
            self.methods[RANGE_ENGINE_ID].fit(range_samples or samples)
        if TREND_ENGINE_ID in self.methods:
            self.methods[TREND_ENGINE_ID].fit(trend_samples or samples)
        if self.fallback:
            self.fallback.fit(samples)

    def calibrate(self, raw: RawConfidence) -> CalibratedConfidence:
        engine = str(raw.engine or "")
        method = self.methods.get(engine)
        if method is not None:
            return method.calibrate(raw)
        if self.fallback is not None:
            return self.fallback.calibrate(raw)
        return Phase14_2ACalibration().calibrate(raw)


def build_calibration_method(name: str) -> CalibrationMethod | EngineSpecificCalibration:
    if name == "phase14_2a":
        return Phase14_2ACalibration()
    if name == "percentile":
        return EngineSpecificCalibration(
            methods={RANGE_ENGINE_ID: PercentileCalibration(), TREND_ENGINE_ID: PercentileCalibration()},
            fallback=PercentileCalibration(),
        )
    if name in ("platt", "isotonic"):
        return EngineSpecificCalibration(
            methods={
                RANGE_ENGINE_ID: ProbabilityCalibration(method=name),
                TREND_ENGINE_ID: ProbabilityCalibration(method=name),
            },
            fallback=ProbabilityCalibration(method=name),
        )
    raise ValueError(f"Unknown calibration method: {name}")


def compare_calibration_methods(
    samples: list[CalibrationSample],
    *,
    methods: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    from tradingbot.ml.research.phase14_6.confidence_distribution import compression_resolved, distribution_stats

    from tradingbot.ml.research.phase14_6.config import (
        COMPRESSION_RESOLVED_MIN_SPREAD,
        COMPRESSION_RESOLVED_MIN_STD,
        CALIBRATION_METHODS,
    )

    names = methods or CALIBRATION_METHODS
    rows: list[dict[str, Any]] = []
    for name in names:
        method = build_calibration_method(name)
        method.fit(samples)
        calibrated_vals = [float(method.calibrate(s.raw).calibrated_value) for s in samples]
        dist = distribution_stats(calibrated_vals)
        rows.append(
            {
                "method": name,
                "distribution": dist,
                "compression_resolved": compression_resolved(
                    dist,
                    min_spread=COMPRESSION_RESOLVED_MIN_SPREAD,
                    min_std=COMPRESSION_RESOLVED_MIN_STD,
                ),
                "mean": dist["mean"],
                "std": dist["std"],
                "p90": dist["p90"],
            }
        )

    rows.sort(key=lambda r: (r["compression_resolved"], r["std"]), reverse=True)
    return {
        "phase": "14.6",
        "methods": rows,
        "best_method": rows[0]["method"] if rows else None,
        "chronological_fit": True,
        "shuffle": False,
    }
