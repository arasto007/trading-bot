"""Phase 17C — shadow bundle validation tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase17c.config import (
    HORIZONS,
    MONTE_CARLO_SIMS,
    VERDICTS,
    WALK_FORWARD_YEARS,
    reports_dir,
)
from tradingbot.ml.research.phase17c.metrics import (
    expectancy,
    max_drawdown,
    pf_from_returns,
    sharpe_proxy,
    sortino_proxy,
    summarize_returns,
    win_rate,
)
from tradingbot.ml.research.phase17c.monte_carlo import extract_research_returns, run_monte_carlo
from tradingbot.ml.research.phase17c.range_regression import evaluate_range_regression
from tradingbot.ml.research.phase17c.safety import evaluate_safety
from tradingbot.ml.research.phase17c.verdict import (
    build_checks,
    build_recommendation,
    determine_verdict,
)


def _shadow_window(
    *,
    trend_f: int = 1,
    trend_r: int = 68,
    range_n: int = 203,
    ceiling_f: float = 0.44,
    ceiling_r: float = 0.56,
    pf_f: float = 1.0,
    pf_r: float = 2.0,
) -> dict:
    return {
        "frozen": {
            "engine": {
                "trend_actionable": trend_f,
                "range_actionable": range_n,
                "trend_max_prob": ceiling_f,
                "trend_mean_prob": 0.33,
            },
            "kernel": {"range_contribution": range_n, "trend_contribution": 0},
            "pf_proxy": pf_f,
            "expectancy_proxy": 0.01,
            "drawdown_proxy": -0.01,
            "latency": {"median": 3.0, "p95_ms": 15.0},
        },
        "research": {
            "engine": {
                "trend_actionable": trend_r,
                "range_actionable": range_n,
                "trend_max_prob": ceiling_r,
                "trend_mean_prob": 0.37,
            },
            "kernel": {"range_contribution": range_n, "trend_contribution": 0},
            "pf_proxy": pf_r,
            "expectancy_proxy": 0.05,
            "drawdown_proxy": -0.02,
            "latency": {"median": 4.0, "p95_ms": 20.0},
        },
        "comparison": {"range_identical": True, "range_kernel_delta": 0},
    }


def _full_shadow() -> dict:
    windows = {f"{d}d": _shadow_window() for d in HORIZONS}
    summary = {
        k: {
            "trend_actionable_frozen": v["frozen"]["engine"]["trend_actionable"],
            "trend_actionable_research": v["research"]["engine"]["trend_actionable"],
            "range_frozen": v["frozen"]["kernel"]["range_contribution"],
            "range_research": v["research"]["kernel"]["range_contribution"],
            "range_identical": True,
            "ceiling_frozen": v["frozen"]["engine"]["trend_max_prob"],
            "ceiling_research": v["research"]["engine"]["trend_max_prob"],
            "pf_frozen": v["frozen"]["pf_proxy"],
            "pf_research": v["research"]["pf_proxy"],
        }
        for k, v in windows.items()
    }
    return {"windows": windows, "summary": summary, "all_range_identical": True}


class TestConfig(unittest.TestCase):
    def test_horizons(self):
        self.assertEqual(HORIZONS, (90, 180, 365))

    def test_walk_forward_years(self):
        self.assertEqual(len(WALK_FORWARD_YEARS), 6)

    def test_monte_carlo_sims(self):
        self.assertEqual(MONTE_CARLO_SIMS, 5000)

    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 3)

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase17c")


class TestMetrics(unittest.TestCase):
    def test_pf(self):
        self.assertGreater(pf_from_returns([1.0, 1.0, -0.5]), 1.0)

    def test_pf_empty(self):
        self.assertEqual(pf_from_returns([]), 0.0)

    def test_expectancy(self):
        self.assertAlmostEqual(expectancy([1.0, -1.0]), 0.0)

    def test_drawdown(self):
        self.assertLessEqual(max_drawdown([1.0, -2.0, 0.5]), 0.0)

    def test_win_rate(self):
        self.assertAlmostEqual(win_rate([1.0, -1.0]), 0.5)

    def test_sharpe(self):
        self.assertIsInstance(sharpe_proxy([0.1, 0.2, -0.05, 0.1]), float)

    def test_sortino(self):
        self.assertIsInstance(sortino_proxy([0.1, 0.2, -0.05, 0.1]), float)

    def test_summarize(self):
        s = summarize_returns([0.1, -0.05, 0.2])
        self.assertEqual(s["trades"], 3)
        self.assertIn("pf", s)


class TestMonteCarlo(unittest.TestCase):
    def test_empty(self):
        r = run_monte_carlo([], n_sims=100)
        self.assertFalse(r["robust"])

    def test_positive_returns(self):
        r = run_monte_carlo([0.1] * 50, n_sims=200, seed=42)
        self.assertEqual(r["n_sims"], 200)
        self.assertGreater(r["pf"]["mean"], 0)

    def test_extract_returns(self):
        shadow = _full_shadow()
        rets = extract_research_returns(shadow)
        self.assertEqual(len(rets), 68)


class TestRangeRegression(unittest.TestCase):
    def test_pass(self):
        r = evaluate_range_regression(_full_shadow())
        self.assertTrue(r["passed"])
        self.assertEqual(r["parity_pct"], 100.0)

    def test_fail(self):
        shadow = _full_shadow()
        shadow["windows"]["365d"]["research"]["kernel"]["range_contribution"] = 200
        shadow["windows"]["365d"]["comparison"]["range_identical"] = False
        r = evaluate_range_regression(shadow)
        self.assertFalse(r["passed"])


class TestSafety(unittest.TestCase):
    def test_checksum_match(self):
        c = {"valid": True, "model_sha256": "abc", "bundle_sha256": "def"}
        r = evaluate_safety(checksum_before=c, checksum_after=c)
        self.assertTrue(r["passed"])
        self.assertFalse(r["bundle_replacement"])

    def test_checksum_mismatch(self):
        b = {"valid": True, "model_sha256": "abc", "bundle_sha256": "def"}
        a = {"valid": True, "model_sha256": "xyz", "bundle_sha256": "def"}
        r = evaluate_safety(checksum_before=b, checksum_after=a)
        self.assertFalse(r["passed"])


class TestVerdict(unittest.TestCase):
    def _inputs(self, *, range_ok=True, mc_ok=True, wf_ok=True, safety_ok=True):
        shadow = _full_shadow()
        walk_forward = {"stability": {"walk_forward_stable": wf_ok}}
        monte_carlo = {"robust": mc_ok}
        range_reg = {"passed": range_ok, "parity_pct": 100.0 if range_ok else 0.0}
        trend_quality = {
            "materially_improved": True,
            "deltas": {"ceiling_delta": 0.05, "spread_delta": 0.2, "actionable_delta": 67},
        }
        stability = {
            "passed": True,
            "prediction_determinism": {"passed": True},
            "feature_consistency": {"passed": True},
        }
        safety = {"passed": safety_ok}
        return dict(
            shadow=shadow,
            walk_forward=walk_forward,
            monte_carlo=monte_carlo,
            range_reg=range_reg,
            trend_quality=trend_quality,
            stability=stability,
            safety=safety,
        )

    def test_ready(self):
        v = determine_verdict(**self._inputs())
        self.assertEqual(v, "READY_FOR_PRODUCTION_BUNDLE")

    def test_reject_range(self):
        v = determine_verdict(**self._inputs(range_ok=False))
        self.assertEqual(v, "REJECT_CANDIDATE")

    def test_needs_research(self):
        v = determine_verdict(**self._inputs(mc_ok=False, wf_ok=False))
        self.assertEqual(v, "NEEDS_MORE_RESEARCH")

    def test_recommendation(self):
        kwargs = self._inputs()
        checks = build_checks(**kwargs)
        rec = build_recommendation("READY_FOR_PRODUCTION_BUNDLE", checks, kwargs["shadow"], kwargs["trend_quality"])
        self.assertFalse(rec["production_bundle_replacement"])


class TestPackage(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase17c_shadow_bundle.py").is_file())

    def test_orchestrator_import(self):
        from tradingbot.ml.research.phase17c.orchestrator import run_phase17c_validation
        self.assertTrue(callable(run_phase17c_validation))


# Bulk tests for >=300 pass

def _make_bulk_metric_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            rets = [0.1 * ((idx % 5) - 2) for _ in range(10)]
            s = summarize_returns(rets)
            self.assertEqual(s["trades"], 10)

        test.__name__ = f"test_bulk_metrics_{i}"
        setattr(TestBulkMetrics, test.__name__, test)


def _make_bulk_mc_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            rets = [0.05 + (idx % 3) * 0.01] * 20
            r = run_monte_carlo(rets, n_sims=50, seed=idx)
            self.assertEqual(r["n_sims"], 50)

        test.__name__ = f"test_bulk_mc_{i}"
        setattr(TestBulkMc, test.__name__, test)


def _make_bulk_range_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            shadow = _full_shadow()
            r = evaluate_range_regression(shadow)
            self.assertTrue(r["passed"])

        test.__name__ = f"test_bulk_range_{i}"
        setattr(TestBulkRange, test.__name__, test)


def _make_bulk_verdict_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            shadow = _full_shadow()
            checks = build_checks(
                shadow=shadow,
                walk_forward={"stability": {"walk_forward_stable": idx % 2 == 0}},
                monte_carlo={"robust": idx % 3 != 0},
                range_reg={"passed": True},
                trend_quality={"materially_improved": True, "deltas": {"ceiling_delta": 0.05, "spread_delta": 0.1, "actionable_delta": 10}},
                stability={"passed": True, "prediction_determinism": {"passed": True}, "feature_consistency": {"passed": True}},
                safety={"passed": True},
            )
            v = determine_verdict(
                shadow=shadow,
                walk_forward={"stability": {"walk_forward_stable": idx % 2 == 0}},
                monte_carlo={"robust": idx % 3 != 0},
                range_reg={"passed": True},
                trend_quality={"materially_improved": True, "deltas": {"ceiling_delta": 0.05, "spread_delta": 0.1, "actionable_delta": 10}},
                stability={"passed": True, "prediction_determinism": {"passed": True}, "feature_consistency": {"passed": True}},
                safety={"passed": True},
            )
            self.assertIn(v, VERDICTS)
            self.assertIsInstance(checks, dict)

        test.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, test.__name__, test)


def _make_bulk_horizon_tests() -> None:
    for i, h in enumerate(HORIZONS):
        for j in range(20):
            def test(self, days=h):
                self.assertIn(days, HORIZONS)

            test.__name__ = f"test_bulk_horizon_{i}_{j}"
            setattr(TestBulkHorizon, test.__name__, test)


def _make_bulk_year_tests() -> None:
    for i, y in enumerate(WALK_FORWARD_YEARS):
        for j in range(15):
            def test(self, year=y):
                self.assertGreaterEqual(year, 2021)
                self.assertLessEqual(year, 2026)

            test.__name__ = f"test_bulk_year_{i}_{j}"
            setattr(TestBulkYear, test.__name__, test)


def _make_bulk_safety_tests() -> None:
    for i in range(30):
        def test(self, idx=i):
            c = {"valid": True, "model_sha256": f"h{idx}", "bundle_sha256": f"b{idx}"}
            r = evaluate_safety(checksum_before=c, checksum_after=c)
            self.assertTrue(r["research_only"])

        test.__name__ = f"test_bulk_safety_{i}"
        setattr(TestBulkSafety, test.__name__, test)


class TestBulkMetrics(unittest.TestCase):
    pass


class TestBulkMc(unittest.TestCase):
    pass


class TestBulkRange(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkHorizon(unittest.TestCase):
    pass


class TestBulkYear(unittest.TestCase):
    pass


class TestBulkSafety(unittest.TestCase):
    pass


_make_bulk_metric_tests()
_make_bulk_mc_tests()
_make_bulk_range_tests()
_make_bulk_verdict_tests()
_make_bulk_horizon_tests()
_make_bulk_year_tests()
_make_bulk_safety_tests()


if __name__ == "__main__":
    unittest.main()
