"""Phase 14.5 — confidence operating point research configuration."""

from __future__ import annotations

from pathlib import Path

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
MIN_TRADE_FLOOR = 300
MONTE_CARLO_SIMS = 1000
MIN_MC_PROFITABLE = 0.95
MIN_WF_ROBUSTNESS = 0.30
PHASE99_BASELINE_PF = 1.06
PHASE14_4_BASELINE_PF = 4.0  # from phase14_4 report baseline_metrics

CONFIDENCE_GRID: tuple[float, ...] = (0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
REGIME_CONFIDENCE_GRID: tuple[float, ...] = (0.35, 0.45, 0.55)
WF_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025, 2026)

# Phase 14.4 recommended fixed quality / risk (research reference only).
DEFAULT_QUALITY_THRESHOLD = 0.50
DEFAULT_MAX_RISK_PERCENT = 0.50
MAX_RESEARCH_BARS = 3_000
GRID_STRIDE = 5


def phase14_5_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase14_5"


def phase14_5_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_5_reports_dir(base_dir) / "final_phase14_5_report.json"
