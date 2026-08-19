"""Phase 13.7 — research configuration and report paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.research.regime_router.config import WALK_FORWARD_YEARS

EXPECTED_DATASET_FINGERPRINT = "70b38325ee1c7e1e"
MIN_TRADES_SOFT = 100
MIN_TRADES_STRONG = 300
MIN_TRADES_PASS = 300
MIN_ROBUSTNESS_PASS = 0.30
PHASE13_5_BASELINE_PF = 0.99
PHASE9_9_BASELINE_PF = 1.06
MONTE_CARLO_SIMULATIONS = 1000
LOW_TRADE_PENALTY_THRESHOLD = 500


def phase13_7_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase13_7"


def phase13_7_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase13_7_reports_dir(base_dir) / "final_phase13_7_report.json"


def phase13_6_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase13_6"


@dataclass(frozen=True)
class RouterVariant:
    key: str
    label: str
    description: str
    policy: str = "A"
    trend_ml_threshold: float = 0.55
    min_confidence: float = 0.0
    range_only: bool = False


ROUTER_VARIANTS: tuple[RouterVariant, ...] = (
    RouterVariant(
        key="router_a",
        label="Router A (Phase 13.5 baseline)",
        description="RANGE->Phase9.9, TREND->Phase13.3+13.4",
        policy="A",
        trend_ml_threshold=0.55,
        min_confidence=0.0,
    ),
    RouterVariant(
        key="router_b",
        label="Router B (conservative trend)",
        description="RANGE->Phase9.9, TREND->Trend ML confidence >= 0.60",
        policy="A",
        trend_ml_threshold=0.60,
        min_confidence=0.0,
    ),
    RouterVariant(
        key="router_c",
        label="Router C (balanced + trade floor)",
        description="RANGE->Phase9.9, TREND->Trend ML >= 0.55, min trades enforced in scoring",
        policy="A",
        trend_ml_threshold=0.55,
        min_confidence=0.0,
    ),
    RouterVariant(
        key="router_d",
        label="Router D (Phase 9.9 only)",
        description="All regimes routed to Phase 9.9",
        policy="RANGE_ONLY",
        trend_ml_threshold=0.55,
        min_confidence=0.0,
        range_only=True,
    ),
)

WALK_FORWARD_YEARS_137 = WALK_FORWARD_YEARS
