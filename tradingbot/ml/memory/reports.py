"""Shadow performance report generation."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.memory.calibration import CalibrationReport, ConfidenceCalibrator
from tradingbot.ml.memory.performance import PerformanceAnalyzer, PerformanceSummary
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.memory.store import DecisionMemoryStore


def shadow_performance_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "shadow_performance.json"


def confidence_calibration_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "confidence_calibration.json"


def session_performance_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "session_performance.json"


def regime_performance_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "regime_performance.json"


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


class ShadowReportGenerator:
    """Generate all Phase 5.2 shadow performance reports."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir

    def generate(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
        *,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
    ) -> dict[str, Any]:
        perf = PerformanceAnalyzer().analyze(decisions, outcomes)
        cal = ConfidenceCalibrator().calibrate(decisions, outcomes)

        shadow_payload = {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            **perf.to_dict(),
            "best_session": self._best_key(perf.by_session, "expected_R"),
            "worst_regime": self._worst_key(perf.by_regime, "expected_R"),
            "confidence_calibration_status": cal.status,
        }

        _write(shadow_performance_path(self.base_dir), shadow_payload)
        _write(confidence_calibration_path(self.base_dir), cal.to_dict())
        _write(
            session_performance_path(self.base_dir),
            {"symbol": symbol.upper(), "sessions": perf.by_session},
        )
        _write(
            regime_performance_path(self.base_dir),
            {"symbol": symbol.upper(), "regimes": perf.by_regime},
        )

        return {
            "shadow_performance": shadow_payload,
            "confidence_calibration": cal.to_dict(),
            "session_performance": perf.by_session,
            "regime_performance": perf.by_regime,
        }

    def generate_from_store(
        self,
        store: DecisionMemoryStore,
        *,
        timeframe: str = "M5",
    ) -> dict[str, Any]:
        decisions = store.load_decisions()
        outcomes = store.load_outcomes_by_id()
        return self.generate(decisions, outcomes, symbol=store.symbol, timeframe=timeframe)

    @staticmethod
    def _best_key(groups: dict[str, dict[str, float]], metric: str) -> str | None:
        if not groups:
            return None
        return max(groups.keys(), key=lambda k: groups[k].get(metric, -1e9))

    @staticmethod
    def _worst_key(groups: dict[str, dict[str, float]], metric: str) -> str | None:
        if not groups:
            return None
        return min(groups.keys(), key=lambda k: groups[k].get(metric, 1e9))
