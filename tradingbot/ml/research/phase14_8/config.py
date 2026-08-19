"""Phase 14.8 — stress validation configuration."""

from __future__ import annotations

from pathlib import Path

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
VALIDATION_PERIODS: tuple[int, ...] = (90, 180, 365)
MARKET_SCENARIOS: tuple[str, ...] = (
    "normal",
    "high_volatility",
    "low_volatility",
    "trend_market",
    "range_market",
    "news_high_atr",
)
WF_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025, 2026)
MONTE_CARLO_SIMS = 5000
MIN_WF_ROBUSTNESS = 0.30
MIN_MC_PROFITABLE = 0.95
MAX_RISK_PERCENT = 0.50
MAX_REGIME_DOMINANCE = 0.90
MAX_RESEARCH_BARS = 4_000
GRID_STRIDE = 5
MIN_POSITIVE_PERIODS = 2


def phase14_8_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase14_8"


def phase14_8_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_8_reports_dir(base_dir) / "phase14_8_final_report.json"
