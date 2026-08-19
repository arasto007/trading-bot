"""Phase 13.10 — trend contribution expansion configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
PHASE99_BASELINE_PF = 1.06
MIN_TREND_TRADES_PASS = 100
MIN_TRADES_REJECT = 100
MIN_TRADES_PREFERRED = 500
MIN_WF_ROBUSTNESS_PASS = 0.30
MIN_MONTE_CARLO_PROFITABLE = 0.95
MONTE_CARLO_SIMS = 1000

THRESHOLD_GRID: tuple[float, ...] = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55)
RULE_VARIANT_KEYS: tuple[str, ...] = ("variant_a", "variant_b", "variant_c", "variant_d")

# Expanding walk-forward: (test_year, train_start_year, train_end_year)
EXPANDING_WF_WINDOWS: tuple[tuple[int, int, int], ...] = (
    (2023, 2021, 2022),
    (2024, 2021, 2023),
    (2025, 2021, 2024),
    (2026, 2021, 2025),
)


def phase13_10_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase13_10"


def phase13_10_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase13_10_reports_dir(base_dir) / "final_phase13_10_report.json"


@dataclass(frozen=True)
class RouterPolicy:
    key: str
    label: str
    description: str
    policy: str = "A"
    trend_ml_threshold: float = 0.45
    relaxed_ml: bool = False
    rules_only: bool = False
    range_only: bool = False


ROUTER_POLICIES: tuple[RouterPolicy, ...] = (
    RouterPolicy(
        key="router_a",
        label="Router A",
        description="RANGE->Phase9.9, TREND->Phase13.8 Trend (RF @ baseline)",
        policy="A",
        trend_ml_threshold=0.45,
    ),
    RouterPolicy(
        key="router_b",
        label="Router B",
        description="RANGE->Phase9.9, TREND->Trend ML relaxed threshold",
        policy="A",
        trend_ml_threshold=0.30,
        relaxed_ml=True,
    ),
    RouterPolicy(
        key="router_c",
        label="Router C",
        description="RANGE->Phase9.9, TREND->Trend rules only (no ML), HIGH_VOL->BLOCK",
        policy="A",
        rules_only=True,
    ),
    RouterPolicy(
        key="router_d",
        label="Router D",
        description="Phase9.9 only (all regimes)",
        policy="RANGE_ONLY",
        range_only=True,
    ),
)
