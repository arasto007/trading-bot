"""Phase 13.8 — trend recovery research configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.research.regime_router.config import WALK_FORWARD_YEARS

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
MIN_TRADES_SOFT = 100
MIN_TRADES_STRONG = 300
MIN_TREND_TRADES_PASS = 100
MIN_PF_PASS = 1.10
MIN_ROBUSTNESS_PASS = 0.30
MONTE_CARLO_SIMS = 1000
THRESHOLD_GRID: tuple[float, ...] = (0.40, 0.45, 0.50, 0.55, 0.60)
ML_MODELS: tuple[str, ...] = ("logistic", "random_forest", "xgboost", "lightgbm")
MAX_HOLD_BARS = 72


def phase13_8_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase13_8"


def phase13_8_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase13_8_reports_dir(base_dir) / "final_phase13_8_report.json"


def phase13_3_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase13_3"


def phase13_4_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase13_4"


def phase13_7_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase13_7"


WALK_FORWARD_YEARS_138 = WALK_FORWARD_YEARS


@dataclass(frozen=True)
class RouterSimVariant:
    key: str
    label: str
    policy: str = "A"
    trend_threshold: float = 0.50
    range_only: bool = False


ROUTER_SIM_VARIANTS: tuple[RouterSimVariant, ...] = (
    RouterSimVariant("router_a", "Router A: Range 9.9 + Best Trend", policy="A", trend_threshold=0.50),
    RouterSimVariant("router_b", "Router B: Range 9.9 + Trend ML 0.50", policy="A", trend_threshold=0.50),
    RouterSimVariant("router_c", "Router C: Range 9.9 + Trend ML 0.55", policy="A", trend_threshold=0.55),
    RouterSimVariant("router_d", "Router D: Phase 9.9 only", policy="RANGE_ONLY", range_only=True),
)
