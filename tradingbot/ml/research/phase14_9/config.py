"""Phase 14.9 — multi-regime stability configuration."""

from __future__ import annotations

import json
from pathlib import Path

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
VALIDATION_PERIODS: tuple[int, ...] = (90, 180, 365)
WF_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025, 2026)
MONTE_CARLO_SIMS = 5000
MIN_TRADE_FLOOR = 300
MIN_PF = 1.2
MIN_WF_ROBUSTNESS = 0.40
MIN_MC_PROFITABLE = 0.95
MIN_POSITIVE_PERIODS = 2
MAX_RESEARCH_BARS = 4_000
GRID_STRIDE = 5
MAX_REGIME_DOMINANCE = 0.92

RANGE_ENGINE_ID = "phase9_9"
TREND_ENGINE_ID = "trend_rf_v40"
DEFAULT_QUALITY_THRESHOLD = 0.50
DEFAULT_MAX_RISK_PERCENT = 0.50


def phase14_9_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase14_9"


def phase14_9_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_9_reports_dir(base_dir) / "final_phase14_9_report.json"


def load_calibration_policy(base_dir: str | Path | None = None) -> dict:
    from tradingbot.ml.research.phase14_6.config import phase14_6_final_report_path

    path = phase14_6_final_report_path(base_dir)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        policy = data.get("recommended_policy") or {}
        return {
            "calibration_method": policy.get("calibration_method", "platt"),
            "confidence_threshold": float(policy.get("confidence_threshold", 0.30)),
        }
    return {"calibration_method": "platt", "confidence_threshold": 0.30}
