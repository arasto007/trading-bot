"""Confidence routing — LOW / MEDIUM / HIGH / EXTREME."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.orchestrator.schema import ConfidenceLevel, OrchestratorSnapshot
from tradingbot.ml.orchestrator.signals import extract_signals, signals_agree


@dataclass
class ConfidenceRouter:
    """Route confidence level from agreement, monitoring, calibration, drift."""

    def route(
        self,
        snapshot: OrchestratorSnapshot,
        ensemble_score: float,
        *,
        strategy_mode: str,
    ) -> str:
        if strategy_mode == "SAFE_MODE":
            return ConfidenceLevel.LOW.value

        signals = extract_signals(snapshot)
        agree = signals_agree(signals)
        score_strength = abs(ensemble_score)

        level = ConfidenceLevel.LOW
        if score_strength >= 0.75 and agree and snapshot.performance_state == "HEALTHY":
            level = ConfidenceLevel.EXTREME
        elif score_strength >= 0.55 and agree:
            level = ConfidenceLevel.HIGH
        elif score_strength >= 0.40:
            level = ConfidenceLevel.MEDIUM

        if snapshot.calibration_error >= 0.20:
            level = ConfidenceLevel.LOW
        elif snapshot.calibration_error >= 0.10 and level == ConfidenceLevel.EXTREME:
            level = ConfidenceLevel.HIGH

        if snapshot.feature_drift_score >= 0.25:
            if level == ConfidenceLevel.EXTREME:
                level = ConfidenceLevel.HIGH
            elif level == ConfidenceLevel.HIGH:
                level = ConfidenceLevel.MEDIUM

        if snapshot.performance_state in ("DEGRADED", "FAILED"):
            if level.value in (ConfidenceLevel.EXTREME.value, ConfidenceLevel.HIGH.value):
                level = ConfidenceLevel.MEDIUM
            else:
                level = ConfidenceLevel.LOW

        return level.value
