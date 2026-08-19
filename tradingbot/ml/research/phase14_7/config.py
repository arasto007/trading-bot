"""Phase 14.7 — end-to-end pipeline validation configuration."""

from __future__ import annotations

import json
from pathlib import Path

EXPECTED_FINGERPRINT = "70b38325ee1c7e1e"
MIN_TRADE_FLOOR = 300
PHASE99_BASELINE_PF = 1.06
MIN_PF_IMPROVEMENT = 0.05
MIN_WF_ROBUSTNESS = 0.30
MIN_MC_PROFITABLE = 0.95
MONTE_CARLO_SIMS = 1000
MAX_RESEARCH_BARS = 3_000
GRID_STRIDE = 5
WF_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025, 2026)

DEFAULT_QUALITY_THRESHOLD = 0.50
DEFAULT_MAX_RISK_PERCENT = 0.50
PHASE99_MIN_CONFIDENCE = 0.55
ROUTER_MIN_CONFIDENCE = 0.55

PIPELINE_BASELINE = "phase9_9_baseline"
PIPELINE_ROUTER = "phase13_10_router"
PIPELINE_FULL = "phase14_full"

REGIMES: tuple[str, ...] = ("RANGE", "TREND", "HIGH_VOLATILITY", "NO_TRADE")
MAX_REGIME_DOMINANCE = 0.85


def phase14_7_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase14_7"


def phase14_7_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase14_7_reports_dir(base_dir) / "phase14_7_final_report.json"


def load_phase14_6_policy(base_dir: str | Path | None = None) -> dict:
    from tradingbot.ml.research.phase14_6.config import phase14_6_final_report_path

    path = phase14_6_final_report_path(base_dir)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        policy = data.get("recommended_policy") or {}
        return {
            "calibration_method": policy.get("calibration_method", "platt"),
            "confidence_threshold": float(policy.get("confidence_threshold", 0.30)),
            "engine_specific": bool(policy.get("engine_specific", True)),
        }
    return {
        "calibration_method": "platt",
        "confidence_threshold": 0.30,
        "engine_specific": True,
    }
