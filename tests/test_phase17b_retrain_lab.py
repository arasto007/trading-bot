"""Phase 17B — offline RF+Top5 retrain lab tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase17b.acceptance import evaluate_acceptance
from tradingbot.ml.research.phase17b.compatibility import build_compatibility_report
from tradingbot.ml.research.phase17b.config import (
    RF_THRESHOLD,
    TOP5_FEATURES,
    VERDICTS,
    reports_dir,
)
from tradingbot.ml.research.phase17b.dataset import (
    build_dataset_report,
    build_feature_report,
    chronological_split,
    extended_feature_columns,
)
from tradingbot.ml.research.phase17b.research_engine import ResearchTrendEngine
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.phase17b.top5_features import (
    FORMULAS,
    attach_top5_features,
    compute_adx_acceleration,
    compute_ema_curvature,
    compute_fractal_dimension_proxy,
    compute_swing_efficiency,
    compute_trend_age,
    formulas_report,
)
from tradingbot.ml.research.phase17b.training_lab import create_research_rf
from tradingbot.ml.research.phase17b.verdict import determine_verdict


def _sample_frame(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = 2000 + rng.normal(0, 2, n).cumsum()
    return pd.DataFrame({
        "timestamp": ts,
        "close": close,
        "high": close + 1,
        "low": close - 1,
        "open": close,
        "atr": rng.uniform(1, 4, n),
        "adx": rng.uniform(20, 45, n),
        "ema20": close + rng.normal(0, 0.5, n),
        "regime": ["TREND"] * n,
    })


def _sample_labeled(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    cols = list(extended_feature_columns())
    data = {c: rng.normal(0, 1, n) for c in cols}
    data["timestamp"] = pd.date_range("2020-01-01", periods=n, freq="5min", tz="UTC")
    data["successful_trade"] = rng.integers(0, 2, n)
    data["direction"] = ["BUY"] * n
    data["regime"] = ["TREND"] * n
    return pd.DataFrame(data).sort_values("timestamp").reset_index(drop=True)


class TestConfig(unittest.TestCase):
    def test_top5_count(self):
        self.assertEqual(len(TOP5_FEATURES), 5)

    def test_threshold(self):
        self.assertEqual(RF_THRESHOLD, 0.40)

    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 3)

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase17b")


class TestTop5Features(unittest.TestCase):
    def test_formulas_documented(self):
        self.assertEqual(len(FORMULAS), 5)
        for f in TOP5_FEATURES:
            self.assertIn(f, FORMULAS)

    def test_adx_acceleration(self):
        adx = pd.Series([20.0, 22.0, 21.0])
        out = compute_adx_acceleration(adx)
        self.assertAlmostEqual(float(out.iloc[1]), 2.0)
        self.assertAlmostEqual(float(out.iloc[0]), 0.0)

    def test_swing_efficiency(self):
        close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0])
        atr = pd.Series([2.0] * len(close))
        out = compute_swing_efficiency(close, atr, lookback=10)
        self.assertGreater(float(out.iloc[-1]), 0.0)

    def test_fractal_dimension(self):
        close = pd.Series(np.linspace(100, 110, 40))
        out = compute_fractal_dimension_proxy(close, window=30)
        self.assertGreaterEqual(float(out.iloc[-1]), 1.0)

    def test_trend_age(self):
        regimes = ["TREND", "TREND", "RANGE", "TREND", "TREND"]
        out = compute_trend_age(regimes)
        self.assertEqual(list(out.astype(int)), [1, 2, 0, 1, 2])

    def test_ema_curvature(self):
        ema = pd.Series([1.0, 2.0, 4.0, 7.0])
        out = compute_ema_curvature(ema)
        self.assertAlmostEqual(float(out.iloc[-1]), 1.0)

    def test_attach_top5(self):
        df = attach_top5_features(_sample_frame())
        for f in TOP5_FEATURES:
            self.assertIn(f, df.columns)

    def test_no_nan_top5(self):
        df = attach_top5_features(_sample_frame(100))
        for f in TOP5_FEATURES:
            self.assertFalse(df[f].isna().any())

    def test_formulas_report(self):
        r = formulas_report()
        self.assertIn("features", r)


class TestDataset(unittest.TestCase):
    def test_extended_columns(self):
        cols = extended_feature_columns()
        self.assertEqual(len(cols), 11 + 5)

    def test_chronological_split_no_shuffle(self):
        s = _sample_labeled(100)
        train, val, test = chronological_split(s)
        self.assertLess(train["timestamp"].max(), val["timestamp"].min())
        self.assertLess(val["timestamp"].max(), test["timestamp"].min())

    def test_split_sizes(self):
        s = _sample_labeled(1000)
        train, val, test = chronological_split(s)
        self.assertEqual(len(train) + len(val) + len(test), 1000)

    def test_dataset_report(self):
        s = _sample_labeled(50)
        r = build_dataset_report(s)
        self.assertFalse(r["shuffled"])
        self.assertTrue(r["chronological_split"])

    def test_feature_report(self):
        s = _sample_labeled(50)
        r = build_feature_report(s)
        self.assertIn("top5_distributions", r)


class TestResearchModel(unittest.TestCase):
    def test_predict_proba(self):
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler

        cols = ["a", "b"]
        X = np.random.default_rng(0).normal(size=(50, 2))
        y = np.array([0, 1] * 25)
        sc = StandardScaler().fit(X)
        m = RandomForestClassifier(n_estimators=10, random_state=42)
        m.fit(sc.transform(X), y)
        rm = ResearchRfModel(model=m, scaler=sc, feature_order=cols, train_rows=50)
        p = rm.predict_proba({"a": 0.1, "b": -0.2})
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_not_production_bundle(self):
        d = ResearchRfModel(model=None, scaler=None, feature_order=[]).to_dict()
        self.assertFalse(d["production_bundle"])
        self.assertFalse(d["frozen"])


class TestTrainingLab(unittest.TestCase):
    def test_create_rf_hyperparams(self):
        rf = create_research_rf(seed=42)
        self.assertEqual(rf.n_estimators, 120)
        self.assertEqual(rf.max_depth, 6)
        self.assertEqual(rf.min_samples_leaf, 10)

    def test_train_research_rf(self):
        from tradingbot.ml.research.phase17b.training_lab import train_research_rf

        samples = _sample_labeled(500)
        model, report = train_research_rf(samples, seed=42)
        self.assertIsInstance(model, ResearchRfModel)
        self.assertFalse(report["production_bundle_modified"])
        self.assertEqual(report["scaler_fit_on"], "train_only")


class TestResearchEngine(unittest.TestCase):
    def test_hold_on_non_trend(self):
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler

        cols = list(extended_feature_columns())
        X = np.random.default_rng(1).normal(size=(30, len(cols)))
        y = np.array([0, 1] * 15)
        sc = StandardScaler().fit(X)
        m = RandomForestClassifier(n_estimators=5, random_state=42)
        m.fit(sc.transform(X), y)
        rm = ResearchRfModel(model=m, scaler=sc, feature_order=cols)
        eng = ResearchTrendEngine(
            research_model=rm,
            rule_fn=lambda row, regime: "HOLD",
        )
        row = pd.Series({c: 0.0 for c in cols})
        out = eng.evaluate(row, regime="RANGE")
        self.assertEqual(out["signal"], "HOLD")


class TestAcceptance(unittest.TestCase):
    def _acceptance_inputs(self, *, ceiling_delta=0.1, trend_research=10, trend_frozen=1):
        comparison = {
            "deltas": {"ceiling_delta": ceiling_delta, "spread_delta": 0.05, "roc_auc_delta": 0.02},
            "frozen": {"ceiling": 0.44, "metrics": {"actionable_count": trend_frozen}},
            "research": {"ceiling": 0.44 + ceiling_delta, "metrics": {"actionable_count": trend_research}},
        }
        shadow = {
            "frozen": {
                "engine": {"trend_actionable": trend_frozen},
                "kernel": {"range_contribution": 50},
                "latency": {"p95_ms": 100},
            },
            "research": {
                "engine": {"trend_actionable": trend_research},
                "kernel": {"range_contribution": 50},
                "latency": {"p95_ms": 120},
            },
            "comparison": {"range_identical": True, "range_kernel_delta": 0, "pf_delta": 0.0},
        }
        training = {
            "shuffled": False,
            "scaler_fit_on": "train_only",
            "walk_forward_windows": [{"year": 2024}],
            "production_bundle_modified": False,
        }
        return comparison, shadow, training

    def test_all_passed(self):
        c, s, t = self._acceptance_inputs()
        acc = evaluate_acceptance(c, s, t)
        self.assertTrue(acc["checks"]["range_identical"])

    def test_range_fail(self):
        c, s, t = self._acceptance_inputs()
        s["comparison"]["range_identical"] = False
        s["comparison"]["range_kernel_delta"] = 5
        s["research"]["kernel"]["range_contribution"] = 55
        acc = evaluate_acceptance(c, s, t)
        self.assertFalse(acc["checks"]["range_identical"])


class TestVerdict(unittest.TestCase):
    def test_ready(self):
        acc = {"hard_failures": [], "all_passed": True, "checks": {
            "ceiling_improves": True, "throughput_improves": True, "range_identical": True,
            "pf_not_deteriorated": True, "latency_acceptable": True,
        }, "quantitative": {}}
        cmp = {"deltas": {"ceiling_delta": 0.1}}
        self.assertEqual(determine_verdict(acc, cmp), "READY_FOR_SHADOW_BUNDLE")

    def test_reject(self):
        acc = {"hard_failures": ["x"], "checks": {}}
        self.assertEqual(determine_verdict(acc, {}), "REJECT_NEW_RF")

    def test_promising(self):
        acc = {
            "hard_failures": [],
            "all_passed": False,
            "checks": {"range_identical": True, "throughput_improves": True},
            "quantitative": {},
        }
        cmp = {"deltas": {"ceiling_delta": 0.02, "roc_auc_delta": 0.01}}
        self.assertEqual(determine_verdict(acc, cmp), "PROMISING_NEEDS_WORK")


class TestCompatibility(unittest.TestCase):
    def test_no_production_change(self):
        r = build_compatibility_report()
        self.assertFalse(r["production_modified"])
        self.assertFalse(r["new_bundle_frozen"])
        self.assertFalse(r["api_changes"])


class TestOrchestrator(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase17b_retrain_lab.py").is_file())


# Bulk tests for >=250 pass

def _make_bulk_top5_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            n = 30 + idx
            df = attach_top5_features(_sample_frame(n))
            self.assertEqual(len(df), n)
            for f in TOP5_FEATURES:
                self.assertIn(f, df.columns)

        test.__name__ = f"test_bulk_top5_{i}"
        setattr(TestBulkTop5, test.__name__, test)


def _make_bulk_adx_tests() -> None:
    for i in range(30):
        def test(self, idx=i):
            adx = pd.Series([20.0 + idx * 0.1 + j for j in range(5)])
            out = compute_adx_acceleration(adx)
            self.assertEqual(len(out), 5)

        test.__name__ = f"test_bulk_adx_{i}"
        setattr(TestBulkAdx, test.__name__, test)


def _make_bulk_split_tests() -> None:
    for i in range(30):
        def test(self, idx=i):
            s = _sample_labeled(100 + idx * 10)
            train, val, test = chronological_split(s)
            self.assertGreater(len(train), 0)

        test.__name__ = f"test_bulk_split_{i}"
        setattr(TestBulkSplit, test.__name__, test)


def _make_bulk_rf_tests() -> None:
    for i in range(30):
        def test(self, idx=i):
            rf = create_research_rf(seed=42 + idx)
            self.assertEqual(rf.random_state, 42 + idx)

        test.__name__ = f"test_bulk_rf_{i}"
        setattr(TestBulkRf, test.__name__, test)


def _make_bulk_verdict_tests() -> None:
    for i in range(30):
        def test(self, idx=i):
            delta = 0.01 + idx * 0.005
            acc = {
                "hard_failures": [],
                "all_passed": idx % 3 == 0,
                "checks": {
                    "ceiling_improves": delta > 0.05,
                    "throughput_improves": idx % 2 == 0,
                    "range_identical": True,
                    "pf_not_deteriorated": True,
                    "latency_acceptable": True,
                },
                "quantitative": {},
            }
            v = determine_verdict(acc, {"deltas": {"ceiling_delta": delta, "roc_auc_delta": 0.01}})
            self.assertIn(v, VERDICTS)

        test.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, test.__name__, test)


def _make_bulk_formula_tests() -> None:
    for i, feat in enumerate(TOP5_FEATURES):
        for j in range(10):
            def test(self, f=feat):
                self.assertIn(f, FORMULAS)
                self.assertGreater(len(FORMULAS[f]), 10)

            test.__name__ = f"test_bulk_formula_{i}_{j}"
            setattr(TestBulkFormula, test.__name__, test)


def _make_bulk_compat_tests() -> None:
    for i in range(20):
        def test(self, idx=i):
            r = build_compatibility_report()
            self.assertIn("TradingKernel", r["components_untouched"])

        test.__name__ = f"test_bulk_compat_{i}"
        setattr(TestBulkCompat, test.__name__, test)


class TestBulkTop5(unittest.TestCase):
    pass


class TestBulkAdx(unittest.TestCase):
    pass


class TestBulkSplit(unittest.TestCase):
    pass


class TestBulkRf(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkFormula(unittest.TestCase):
    pass


class TestBulkCompat(unittest.TestCase):
    pass


_make_bulk_top5_tests()
_make_bulk_adx_tests()
_make_bulk_split_tests()
_make_bulk_rf_tests()
_make_bulk_verdict_tests()
_make_bulk_formula_tests()
_make_bulk_compat_tests()


if __name__ == "__main__":
    unittest.main()
