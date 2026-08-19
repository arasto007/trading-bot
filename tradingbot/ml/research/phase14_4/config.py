"""Phase 14.4 — signal optimization research configuration."""

from __future__ import annotations

from pathlib import Path

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
MIN_TRADES_PASS = 300
MONTE_CARLO_SIMS = 1000

CONFIDENCE_GRID: tuple[float, ...] = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
QUALITY_GRID: tuple[float, ...] = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75)
RISK_CAP_GRID: tuple[float, ...] = (0.10, 0.25, 0.40, 0.50)

# Six expanding walk-forward windows: (test_year, train_start, train_end)
WF_WINDOWS: tuple[tuple[int, int, int], ...] = (
    (2022, 2021, 2021),
    (2023, 2021, 2022),
    (2024, 2021, 2023),
    (2025, 2021, 2024),
    (2026, 2021, 2025),
    (2021, 2021, 2020),
)

MAX_HOLD_BARS = 72
DEFAULT_RR = 2.0
MAX_RESEARCH_BARS = 3_000
GRID_STRIDE = 5


def phase14_4_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase14_4"


def phase14_4_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_4_reports_dir(base_dir) / "final_phase14_4_report.json"
