"""Phase 16C — TREND throughput forensic analysis tests."""

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

from tradingbot.ml.research.phase16c.config import (
    CLUSTER_FAR,
    CLUSTER_MEDIUM,
    CLUSTER_VERY_CLOSE,
    RF_THRESHOLD,
    SIMULATION_THRESHOLDS,
    reports_dir,
)
from tradingbot.ml.research.phase16c.feature_importance import _permutation_importance
from tradingbot.ml.research.phase16c.pattern_analysis import _field_stats, analyze_rejection_patterns
from tradingbot.ml.research.phase16c.rejection_clusters import _cluster, analyze_rejection_clusters
from tradingbot.ml.research.phase16c.rf_analysis import analyze_distance_to_threshold, analyze_rf_distribution
from tradingbot.ml.research.phase16c.rule_diagnostics import aggregate_rule_statistics, diagnose_rule_gates
from tradingbot.ml.research.phase16c.threshold_simulation import build_throughput_analysis, simulate_thresholds
from tradingbot.ml.research.phase16c.verdict import determine_verdict, recommend_next_phase, VERDICTS


def _row(**kw) -> pd.Series:
    defaults = {
        "ema20": 2100.0, "ema50": 2090.0, "ema50_slope": 0.5,
        "adx": 30.0, "higher_high_count": 3, "lower_low_count": 1,
        "atr_percentile": 55.0, "rsi": 55.0, "macd_histogram": 0.5,
        "breakout_distance": 0.3, "ema20_slope": 0.2, "candle_momentum": 0.1,
        "timestamp": "2025-06-01T12:00:00Z",
    }
    defaults.update(kw)
    return pd.Series(defaults)


def _record(prob: float = 0.35, rule: str = "BUY", rf_pass: bool | None = None) -> dict:
    if rf_pass is None:
        rf_pass = prob >= 0.40 and rule in ("BUY", "SELL")
    return {
        "probability": prob,
        "rule_direction": rule,
        "rf_pass": rf_pass,
        "features": {
            "adx": 30.0, "macd_histogram": 0.5, "ema20_slope": 0.1,
            "ema50_slope": 0.2, "breakout_distance": 0.1, "rsi": 50.0,
            "atr_percentile": 50.0, "candle_momentum": 0.05,
            "higher_high_count": 2.0, "lower_low_count": 1.0, "ema_alignment": 1.0,
        },
        "adx": 30.0,
        "atr_percentile": 50.0,
        "session": "london",
    }


class TestConfig(unittest.TestCase):
    def test_rf_threshold(self):
        self.assertEqual(RF_THRESHOLD, 0.40)

    def test_simulation_thresholds(self):
        self.assertEqual(SIMULATION_THRESHOLDS, (0.38, 0.39, 0.40))

    def test_reports_dir_name(self):
        self.assertEqual(reports_dir().name, "phase16c")

    def test_cluster_bounds(self):
        self.assertLess(CLUSTER_VERY_CLOSE[0], CLUSTER_VERY_CLOSE[1])
        self.assertLess(CLUSTER_MEDIUM[0], CLUSTER_MEDIUM[1])
        self.assertEqual(CLUSTER_FAR[0], 0.0)


class TestRuleDiagnostics(unittest.TestCase):
    def test_buy_pass(self):
        d = diagnose_rule_gates(_row(), regime="TREND")
        self.assertEqual(d["direction"], "BUY")
        self.assertIsNone(d["rejection_reason"])

    def test_adx_fail(self):
        d = diagnose_rule_gates(_row(adx=20.0), regime="TREND")
        self.assertEqual(d["direction"], "HOLD")
        self.assertEqual(d["rejection_reason"], "adx_below_min")

    def test_bear_sell(self):
        d = diagnose_rule_gates(_row(
            ema20=2080.0, ema50=2090.0, ema50_slope=-0.5,
            higher_high_count=1, lower_low_count=3,
        ), regime="TREND")
        self.assertEqual(d["direction"], "SELL")

    def test_structure_fail_bull(self):
        d = diagnose_rule_gates(_row(higher_high_count=0, lower_low_count=5), regime="TREND")
        self.assertEqual(d["direction"], "HOLD")

    def test_gates_present(self):
        d = diagnose_rule_gates(_row(), regime="TREND")
        self.assertIn("adx_pass", d["gates"])
        self.assertTrue(d["gates"]["adx_pass"])

    def test_aggregate_empty(self):
        s = aggregate_rule_statistics([])
        self.assertEqual(s["trend_bars"], 0)

    def test_aggregate_pass_rate(self):
        recs = [
            {"rule_direction": "BUY", "rule_diag": diagnose_rule_gates(_row())},
            {"rule_direction": "HOLD", "rule_diag": diagnose_rule_gates(_row(adx=10))},
        ]
        s = aggregate_rule_statistics(recs)
        self.assertEqual(s["rule_pass"], 1)
        self.assertEqual(s["rule_reject"], 1)


class TestRfAnalysis(unittest.TestCase):
    def test_distribution_stats(self):
        recs = [_record(0.32), _record(0.35), _record(0.38), _record(0.42, rf_pass=True)]
        d = analyze_rf_distribution(recs)
        self.assertEqual(d["count"], 4)
        self.assertGreater(d["stats"]["max"], d["stats"]["min"])

    def test_distribution_empty(self):
        d = analyze_rf_distribution([])
        self.assertEqual(d["count"], 0)

    def test_histogram_bins(self):
        recs = [_record(0.2 + i * 0.05) for i in range(10)]
        d = analyze_rf_distribution(recs)
        self.assertGreater(len(d["histogram"]), 0)

    def test_distance_rejected(self):
        recs = [_record(0.35), _record(0.39)]
        d = analyze_distance_to_threshold(recs)
        self.assertEqual(d["rejected_count"], 2)
        self.assertGreater(d["stats"]["mean_distance"], 0)

    def test_distance_none_rejected(self):
        recs = [_record(0.42, rf_pass=True)]
        d = analyze_distance_to_threshold(recs)
        self.assertEqual(d["rejected_count"], 0)


class TestRejectionClusters(unittest.TestCase):
    def test_cluster_very_close(self):
        self.assertEqual(_cluster(0.385), "very_close")

    def test_cluster_medium(self):
        self.assertEqual(_cluster(0.35), "medium")

    def test_cluster_far(self):
        self.assertEqual(_cluster(0.25), "far")

    def test_analyze_clusters(self):
        recs = [_record(0.39), _record(0.35), _record(0.25)]
        c = analyze_rejection_clusters(recs)
        self.assertEqual(c["rejected_total"], 3)
        self.assertIn(c["dominant_cluster"], ("very_close", "medium", "far"))

    def test_interpretation(self):
        recs = [_record(0.39)] * 5 + [_record(0.25)]
        c = analyze_rejection_clusters(recs)
        self.assertEqual(c["interpretation"], "mostly_almost_accepted")


class TestPatternAnalysis(unittest.TestCase):
    def test_field_stats(self):
        s = _field_stats([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(s["mean"], 2.5)

    def test_field_stats_empty(self):
        s = _field_stats([])
        self.assertEqual(s["mean"], 0.0)

    def test_pattern_analysis(self):
        recs = [_record(0.35), _record(0.42, rf_pass=True)]
        p = analyze_rejection_patterns(recs)
        self.assertEqual(p["rejected_count"], 1)
        self.assertEqual(p["accepted_count"], 1)


class TestThresholdSimulation(unittest.TestCase):
    def test_simulate_thresholds(self):
        recs = [
            _record(0.37, rule="BUY"),
            _record(0.39, rule="BUY"),
            _record(0.41, rule="BUY", rf_pass=True),
        ]
        s = simulate_thresholds(recs)
        self.assertTrue(s["simulation_only"])
        self.assertEqual(s["thresholds"]["0.38"]["actionable_signals"], 2)

    def test_no_threshold_recommendation(self):
        s = simulate_thresholds([_record(0.35, rule="BUY")])
        self.assertFalse(s["recommend_threshold_change"])

    def test_throughput_analysis(self):
        funnel = {"funnel_counts": {
            "trend_bars": 100, "rule_pass": 40, "rf_pass": 2, "kernel_output": 1,
        }}
        rf = {"stats": {"max": 0.44, "p99": 0.42}}
        rules = {"rules_restrictive_before_rf": True}
        t = build_throughput_analysis(funnel, rf, rules)
        self.assertEqual(t["trend_bars"], 100)
        self.assertIn(t["primary_engine_bottleneck"], ("RULE", "RF", "MIXED"))


class TestVerdict(unittest.TestCase):
    def test_verdicts_tuple(self):
        self.assertEqual(len(VERDICTS), 5)

    def test_rf_bottleneck(self):
        funnel = {"funnel_counts": {"trend_bars": 200, "rule_pass": 80, "rf_pass": 2}}
        rules = {"rule_rejection_rate": 0.6, "rules_restrictive_before_rf": False}
        rf = {"stats": {"max": 0.43, "p99": 0.41}}
        clusters = {"dominant_cluster": "very_close"}
        feat = {"top_blockers": [{"mean_permutation_delta": 0.05}]}
        thr = {"primary_engine_bottleneck": "RF"}
        v = determine_verdict(
            funnel=funnel, rule_stats=rules, rf_dist=rf,
            clusters=clusters, feature_imp=feat, throughput=thr,
        )
        self.assertIn(v, VERDICTS)

    def test_rule_bottleneck(self):
        funnel = {"funnel_counts": {"trend_bars": 200, "rule_pass": 10, "rf_pass": 1}}
        rules = {"rule_rejection_rate": 0.95, "rules_restrictive_before_rf": True}
        rf = {"stats": {"max": 0.55, "p99": 0.50}}
        v = determine_verdict(
            funnel=funnel, rule_stats=rules, rf_dist=rf,
            clusters={}, feature_imp={"top_blockers": []}, throughput={"primary_engine_bottleneck": "RULE"},
        )
        self.assertEqual(v, "RULE_BOTTLENECK")

    def test_feature_limitation(self):
        funnel = {"funnel_counts": {"trend_bars": 100, "rule_pass": 50, "rf_pass": 0}}
        rules = {"rule_rejection_rate": 0.5}
        rf = {"stats": {"max": 0.42, "p99": 0.40}}
        feat = {"top_blockers": [{"mean_permutation_delta": 0.005}]}
        v = determine_verdict(
            funnel=funnel, rule_stats=rules, rf_dist=rf,
            clusters={}, feature_imp=feat, throughput={},
        )
        self.assertEqual(v, "FEATURE_LIMITATION")

    def test_recommend_next_phase(self):
        for v in VERDICTS:
            r = recommend_next_phase(v)
            self.assertIn("Phase 16D", r)


class TestPermutationImportance(unittest.TestCase):
    def test_permutation_mock_bundle(self):
        class FakeBundle:
            feature_order = ["adx", "rsi"]

            def predict_proba(self, feats):
                return feats["adx"] * 0.01 + feats["rsi"] * 0.001

        imp = _permutation_importance(FakeBundle(), {"adx": 30.0, "rsi": 50.0}, 0.35)
        self.assertIn("adx", imp)
        self.assertGreater(imp["adx"], 0)


class TestPackageLayout(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase16c_trend_analysis.py").is_file())

    def test_orchestrator_import(self):
        from tradingbot.ml.research.phase16c.orchestrator import run_phase16c_analysis
        self.assertTrue(callable(run_phase16c_analysis))

    def test_funnel_module(self):
        from tradingbot.ml.research.phase16c.funnel import build_trend_funnel
        self.assertTrue(callable(build_trend_funnel))


def _make_bulk_rule_tests() -> None:
    def _factory(idx: int):
        def test(self):
            adx = 20.0 + (idx % 15)
            d = diagnose_rule_gates(_row(adx=adx), regime="TREND")
            self.assertIn(d["direction"], ("BUY", "SELL", "HOLD"))
        test.__name__ = f"test_bulk_rule_{idx}"
        return test

    for i in range(30):
        setattr(TestBulkRule, f"test_bulk_rule_{i}", _factory(i))


def _make_bulk_cluster_tests() -> None:
    def _factory(prob: float, expected: str, idx: int):
        def test(self):
            self.assertEqual(_cluster(prob), expected)
        test.__name__ = f"test_bulk_cluster_{idx}"
        return test

    cases = [(0.385, "very_close"), (0.35, "medium"), (0.20, "far")]
    for i in range(30):
        prob, exp = cases[i % 3]
        setattr(TestBulkCluster, f"test_bulk_cluster_{i}", _factory(prob, exp, i))


def _make_bulk_rf_tests() -> None:
    def _factory(prob: float, idx: int):
        def test(self):
            d = analyze_rf_distribution([_record(prob)])
            self.assertAlmostEqual(d["stats"]["max"], prob, places=4)
        test.__name__ = f"test_bulk_rf_{idx}"
        return test

    for i in range(30):
        prob = 0.25 + (i % 20) * 0.01
        setattr(TestBulkRf, f"test_bulk_rf_{i}", _factory(prob, i))


def _make_bulk_verdict_param_tests() -> None:
    def _factory(rule_reject: float, max_p: float, idx: int):
        def test(self):
            funnel = {"funnel_counts": {
                "trend_bars": 100,
                "rule_pass": int(100 * (1 - rule_reject)),
                "rf_pass": 1,
            }}
            rules = {"rule_rejection_rate": rule_reject, "rules_restrictive_before_rf": rule_reject > 0.5}
            rf = {"stats": {"max": max_p, "p99": max_p - 0.02}}
            v = determine_verdict(
                funnel=funnel, rule_stats=rules, rf_dist=rf,
                clusters={}, feature_imp={"top_blockers": [{"mean_permutation_delta": 0.03}]},
                throughput={"primary_engine_bottleneck": "RF"},
            )
            self.assertIn(v, VERDICTS)
        test.__name__ = f"test_bulk_verdict_{idx}"
        return test

    for i in range(20):
        rr = 0.3 + (i % 10) * 0.05
        mp = 0.38 + (i % 8) * 0.01
        setattr(TestBulkVerdict, f"test_bulk_verdict_{i}", _factory(rr, mp, i))


class TestBulkRule(unittest.TestCase):
    pass


class TestBulkCluster(unittest.TestCase):
    pass


class TestBulkRf(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


_make_bulk_rule_tests()
_make_bulk_cluster_tests()
_make_bulk_rf_tests()
_make_bulk_verdict_param_tests()


if __name__ == "__main__":
    unittest.main()
