"""Phase 14.6 — calibration recovery research configuration."""

from __future__ import annotations

from pathlib import Path

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
MIN_TRADE_FLOOR = 300
PHASE99_BASELINE_PF = 1.06
MIN_WF_ROBUSTNESS = 0.30
MIN_MC_PROFITABLE = 0.95
MONTE_CARLO_SIMS = 1000
MAX_RESEARCH_BARS = 3_000
GRID_STRIDE = 5
TRAIN_SPLIT = 0.70

THRESHOLD_GRID: tuple[float, ...] = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55)
CONFIDENCE_BUCKETS: tuple[tuple[float, float], ...] = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.0),
)
WF_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025, 2026)
CALIBRATION_METHODS: tuple[str, ...] = ("phase14_2a", "percentile", "platt", "isotonic")

DEFAULT_QUALITY_THRESHOLD = 0.50
DEFAULT_MAX_RISK_PERCENT = 0.50
COMPRESSION_RESOLVED_MIN_SPREAD = 0.25
COMPRESSION_RESOLVED_MIN_STD = 0.12

RANGE_ENGINE_ID = "phase9_9"
TREND_ENGINE_ID = "trend_rf_v40"


def phase14_6_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase14_6"


def phase14_6_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_6_reports_dir(base_dir) / "phase14_6_final_report.json"
