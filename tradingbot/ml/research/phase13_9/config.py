"""Phase 13.9 — configuration and report paths."""

from __future__ import annotations

from pathlib import Path

from tradingbot.ml.research.regime_router.config import WALK_FORWARD_YEARS

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
MIN_TRADES_REJECT = 300
MIN_SIGNALS_TARGET = 500
MIN_SIGNALS_PREFERRED = 3000
MONTE_CARLO_SIMS = 1000

# Trend-critical columns — never overwrite with dataset merge.
TREND_PROTECTED_COLUMNS: tuple[str, ...] = (
    "ema20",
    "ema50",
    "ema200",
    "ema_alignment",
    "ema20_slope",
    "ema50_slope",
    "adx",
    "atr",
    "atr_percentile",
    "rsi",
    "macd_histogram",
    "higher_high_count",
    "lower_low_count",
    "breakout_distance",
    "candle_momentum",
)

# Phase 9.9 dataset features stored under dedicated prefixes.
PHASE99_FEATURE_MAP: dict[str, str] = {
    "ema50_slope": "phase99_ema50_slope",
    "candle_direction": "phase99_candle_direction",
    "structure_distance": "phase99_structure_distance",
    "ema_cross_state": "phase99_ema_cross_state",
}


def phase13_9_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase13_9"


def phase13_9_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase13_9_reports_dir(base_dir) / "phase13_9_final_report.json"


WALK_FORWARD_YEARS_139 = WALK_FORWARD_YEARS
