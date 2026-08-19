"""Phase 16B — unit tests for validation layer (no production mutations)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingbot.ml.research.phase16b.alignment_metrics import _psi
from tradingbot.ml.research.phase16b.config import reports_dir
from tradingbot.ml.research.phase16b.validator import (
    final_verdict,
    run_hard_checks,
    _check_inflation,
    _check_psi,
)


def test_psi_identical_distributions_near_zero():
    x = np.linspace(0, 1, 200)
    assert _psi(x, x) < 0.05


def test_psi_shifted_distributions_elevated():
    a = np.random.default_rng(0).normal(0, 1, 500)
    b = np.random.default_rng(1).normal(3, 1, 500)
    assert _psi(a, b) > 0.25


def test_check_psi_fails_above_one():
    ok, msg = _check_psi({"max_psi_after": 1.5})
    assert not ok
    assert "PSI" in msg


def test_check_psi_passes_below_one():
    ok, msg = _check_psi({"max_psi_after": 0.2})
    assert ok
    assert msg == ""


def test_check_inflation_threshold():
    ok, _ = _check_inflation(10.0)
    assert ok
    ok, msg = _check_inflation(25.0)
    assert not ok
    assert "inflation" in msg.lower()


def test_hard_checks_trend_zero_fails():
    windows = {
        "90d": {"strides": {"5": {"engine_health": {"TREND": {"buy": 0, "sell": 0}}, "kernel": {"actionable": 10, "range_contribution": 10}}}},
        "180d": {"strides": {"5": {"engine_health": {"TREND": {"buy": 0, "sell": 0}}, "kernel": {"actionable": 10, "range_contribution": 10}}}},
        "365d": {"strides": {"5": {"engine_health": {"TREND": {"buy": 0, "sell": 0}}, "kernel": {"actionable": 10, "range_contribution": 10}}}},
    }
    result = run_hard_checks(
        windows=windows,
        alignment_stability={"max_psi_after": 0.1},
        inflation_pct=0.0,
    )
    assert not result["passed"]
    assert any("TREND" in f for f in result["failures"])


def test_hard_checks_pass_healthy():
    windows = {
        "90d": {
            "strides": {
                "5": {
                    "engine_health": {
                        "TREND": {"buy": 2, "sell": 1, "actionable_rate": 0.01},
                        "RANGE": {"buy": 5, "sell": 3},
                    },
                    "kernel": {"actionable": 8, "range_contribution": 5, "trend_contribution": 3},
                }
            }
        },
        "180d": {
            "strides": {
                "5": {
                    "engine_health": {
                        "TREND": {"buy": 3, "sell": 1, "actionable_rate": 0.012},
                        "RANGE": {"buy": 6, "sell": 2},
                    },
                    "kernel": {"actionable": 10, "range_contribution": 6, "trend_contribution": 4},
                }
            }
        },
    }
    result = run_hard_checks(
        windows=windows,
        alignment_stability={"max_psi_after": 0.15},
        inflation_pct=5.0,
    )
    assert result["passed"]


def test_final_verdict_ready():
    windows = {
        "365d": {
            "strides": {
                "5": {
                    "engine_health": {"TREND": {"buy": 2, "sell": 1, "actionable_rate": 0.01}},
                    "kernel": {"actionable": 10, "range_contribution": 5},
                }
            }
        }
    }
    hard = {"passed": True, "failures": []}
    stress = {
        "regime_shock": {"passed": True},
        "distribution_shift": {"passed": True},
        "threshold_sensitivity": {"passed": True},
    }
    assert final_verdict(hard, windows, stress) == "READY_FOR_PHASE16C"


def test_final_verdict_rework_on_hard_fail():
    assert final_verdict({"passed": False, "failures": ["x"]}, {}, {}) == "NEEDS_REWORK"


def test_final_verdict_minor_tuning_on_stress_fail():
    windows = {
        "365d": {
            "strides": {
                "5": {
                    "engine_health": {"TREND": {"buy": 1, "sell": 0, "actionable_rate": 0.01}},
                    "kernel": {"actionable": 5, "range_contribution": 4},
                }
            }
        }
    }
    hard = {"passed": True, "failures": []}
    stress = {
        "regime_shock": {"passed": False},
        "distribution_shift": {"passed": True},
        "threshold_sensitivity": {"passed": True},
    }
    assert final_verdict(hard, windows, stress) == "NEEDS_MINOR_TUNING"


def test_reports_dir_path():
    p = reports_dir()
    assert p.name == "phase16b"


def test_cli_script_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "run_phase16b_kernel_validation.py").is_file()


def test_orchestrator_importable():
    from tradingbot.ml.research.phase16b.orchestrator import run_phase16b

    assert callable(run_phase16b)
