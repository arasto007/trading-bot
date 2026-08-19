"""Phase 14.10 — walk-forward stability recovery configuration."""

from __future__ import annotations

import json
from pathlib import Path

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
WF_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025, 2026)
THRESHOLD_GRID: tuple[float, ...] = (0.25, 0.30, 0.35, 0.40)
BASELINE_THRESHOLD = 0.30
MIN_WF_ROBUSTNESS = 0.40
MIN_YEAR_BARS = 200
MONTE_CARLO_SIMS_PER_YEAR = 1000
MAX_RESEARCH_BARS = 4_000
GRID_STRIDE = 5
REGIMES = ("TREND", "RANGE", "HIGH_VOLATILITY", "NO_TRADE")
FEATURE_DRIFT_COLUMNS: tuple[str, ...] = (
    "ema20_slope",
    "ema50_slope",
    "ema200_slope",
    "adx",
    "atr",
    "atr_percentile",
    "rsi",
    "macd_histogram",
    "candle_momentum",
    "phase99_ema50_slope",
    "phase99_candle_direction",
    "phase99_structure_distance",
)
CONFIDENCE_HIST_BINS = 10


def phase14_10_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase14_10"


def phase14_10_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_10_reports_dir(base_dir) / "final_phase14_10_report.json"


def load_calibration_policy(base_dir: str | Path | None = None) -> dict:
    from tradingbot.ml.research.phase14_6.config import phase14_6_final_report_path

    path = phase14_6_final_report_path(base_dir)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        policy = data.get("recommended_policy") or {}
        return {
            "calibration_method": policy.get("calibration_method", "platt"),
            "confidence_threshold": float(policy.get("confidence_threshold", BASELINE_THRESHOLD)),
        }
    return {"calibration_method": "platt", "confidence_threshold": BASELINE_THRESHOLD}


def slice_year(
    candles,
    dataset,
    year: int,
):
    """Return (candles, dataset) sliced to a single calendar year."""
    import pandas as pd

    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.loc[c.index.year == year]
    ds = None
    if dataset is not None and not dataset.empty:
        ds = dataset.copy()
        ds["timestamp"] = pd.to_datetime(ds["timestamp"], utc=True)
        ds = ds[ds["timestamp"].dt.year == year]
    return c.sort_index(), ds


def regime_pct_from_records(records: list) -> dict[str, float]:
    total = len(records) or 1
    counts = {r: 0 for r in REGIMES}
    for rec in records:
        key = str(rec.get("regime", "NO_TRADE"))
        if key not in counts:
            key = "NO_TRADE"
        counts[key] += 1
    return {k: round(v / total, 4) for k, v in counts.items()}
