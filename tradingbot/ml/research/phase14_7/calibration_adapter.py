"""Phase 14.7 — Phase 14.6 Platt calibration loader (read-only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationMethod, build_calibration_method
from tradingbot.ml.research.phase14_6.config import phase14_6_final_report_path
from tradingbot.ml.research.phase14_6.research_calibrator import (
    ResearchCalibratedAdapter,
    ResearchCalibrationPolicy,
    build_calibration_samples,
)
from tradingbot.ml.research.phase14_7.config import load_phase14_6_policy


def load_recovered_calibration(
    candles,
    dataset,
    *,
    base_dir: str | Path | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: Any | None = None,
) -> tuple[CalibrationMethod, dict[str, Any]]:
    policy = load_phase14_6_policy(base_dir)
    method_name = str(policy["calibration_method"])
    method = build_calibration_method(method_name)
    samples = build_calibration_samples(
        candles,
        dataset,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        stride=stride,
        range_engine=range_engine,
        trend_engine=trend_engine,
        unified=unified,
    )
    method.fit(samples)
    policy["phase14_6_report_exists"] = phase14_6_final_report_path(base_dir).is_file()
    policy["samples_fitted"] = len(samples)
    return method, policy


def build_calibrated_adapter(
    calibration_method: CalibrationMethod,
    *,
    confidence_threshold: float,
) -> ResearchCalibratedAdapter:
    return ResearchCalibratedAdapter(
        DecisionOrchestrator(),
        calibration_method=calibration_method,
        policy=ResearchCalibrationPolicy(min_calibrated_confidence=confidence_threshold),
    )
