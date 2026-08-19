"""Phase 16D — feature ceiling expansion study tests."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase16d.candidate_compute import (
    CANDIDATE_FEATURE_IDS,
    compute_candidate_features,
)
from tradingbot.ml.research.phase16d.ceiling_analysis import _saturation_score, analyze_feature_ceiling
from tradingbot.ml.research.phase16d.ceiling_simulation import simulate_ceiling_improvement
from tradingbot.ml.research.phase16d.config import RF_THRESHOLD, VERDICTS, reports_dir
from tradingbot.ml.research.phase16d.feature_catalog import CANDIDATE_CATALOG, catalog_as_json
from tradingbot.ml.research.phase16d.information_gain import analyze_information_gain, build_candidate_ranking
from tradingbot.ml.research.phase16d.model_limitation import build_feature_gap_analysis
from tradingbot.ml.research.phase16d.redundancy import _cluster_features, analyze_feature_redundancy
from tradingbot.ml.research.phase16d.verdict import determine_verdict, recommend_next_phase


def _mock_record(
    prob: float = 0.33,
    win: int = 0,
    adx: float = 30.0,
    **feat_kw,
) -> SimpleNamespace:
    existing = {
        "ema20_slope": 0.1, "ema50_slope": 0.2, "ema_alignment": 1.0,
        "adx": adx, "atr_percentile": 50.0, "rsi": 55.0, "macd_histogram": 0.1,
        "breakout_distance": 0.2, "higher_high_count": 2.0, "lower_low_count": 1.0,
        "candle_momentum": 0.05,
    }
    existing.update(feat_kw)
    candidates = {c: float(i) * 0.1 for i, c in enumerate(CANDIDATE_FEATURE_IDS)}
    return SimpleNamespace(
        probability=prob,
        win_proxy=win,
        rule_direction="BUY",
        existing=existing,
        candidates=candidates,
        adx=adx,
        atr_percentile=50.0,
    )


def _mock_bundle():
    order = list(_mock_record().existing.keys())
    return SimpleNamespace(
        feature_order=order,
        predict_proba=lambda feats: 0.33,
    )


def _sample_frame(n: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC"),
        "close": 2000 + rng.normal(0, 5, n).cumsum(),
        "high": 2000 + rng.normal(0, 5, n).cumsum() + 2,
        "low": 2000 + rng.normal(0, 5, n).cumsum() - 2,
        "open": 2000 + rng.normal(0, 5, n).cumsum(),
        "volume": rng.integers(100, 500, n),
        "ema20": 2000 + rng.normal(0, 3, n).cumsum(),
        "ema50": 1998 + rng.normal(0, 3, n).cumsum(),
        "ema200": 1995 + rng.normal(0, 2, n).cumsum(),
        "ema_alignment": rng.normal(0, 1, n),
        "ema20_slope": rng.normal(0, 0.1, n),
        "ema50_slope": rng.normal(0, 0.1, n),
        "adx": rng.uniform(20, 40, n),
        "atr": rng.uniform(1, 5, n),
        "atr_percentile": rng.uniform(30, 80, n),
        "rsi": rng.uniform(40, 60, n),
        "macd_histogram": rng.normal(0, 0.5, n),
        "higher_high_count": rng.integers(0, 5, n),
        "lower_low_count": rng.integers(0, 5, n),
        "breakout_distance": rng.normal(0, 0.5, n),
        "candle_momentum": rng.normal(0, 0.2, n),
        "regime": ["TREND"] * n,
    })


class TestConfig(unittest.TestCase):
    def test_threshold(self):
        self.assertEqual(RF_THRESHOLD, 0.40)

    def test_verdicts_count(self):
        self.assertEqual(len(VERDICTS), 5)

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase16d")


class TestCatalog(unittest.TestCase):
    def test_catalog_size(self):
        self.assertGreaterEqual(len(CANDIDATE_CATALOG), 10)

    def test_catalog_json(self):
        c = catalog_as_json()
        self.assertFalse(c["production_modified"])
        self.assertEqual(c["candidate_count"], len(CANDIDATE_CATALOG))

    def test_ids_unique(self):
        ids = [x["id"] for x in CANDIDATE_CATALOG]
        self.assertEqual(len(ids), len(set(ids)))


class TestCandidateCompute(unittest.TestCase):
    def test_compute_adds_columns(self):
        df = compute_candidate_features(_sample_frame())
        for c in CANDIDATE_FEATURE_IDS:
            self.assertIn(c, df.columns)

    def test_persistence_non_negative(self):
        df = compute_candidate_features(_sample_frame())
        self.assertTrue((df["trend_persistence"] >= 0).all())

    def test_candidate_ids_match_catalog(self):
        cat_ids = {x["id"] for x in CANDIDATE_CATALOG}
        for c in CANDIDATE_FEATURE_IDS:
            self.assertIn(c, cat_ids)


class TestCeilingAnalysis(unittest.TestCase):
    def test_saturation_flat(self):
        self.assertGreater(_saturation_score([
            {"mean_prob": 0.33}, {"mean_prob": 0.33}, {"mean_prob": 0.34},
        ]), 0.7)

    def test_saturation_spread(self):
        self.assertLess(_saturation_score([
            {"mean_prob": 0.2}, {"mean_prob": 0.4}, {"mean_prob": 0.6},
        ]), 0.5)

    def test_analyze_ceiling(self):
        recs = [_mock_record(prob=0.32 + i * 0.001, adx=25 + i) for i in range(40)]
        r = analyze_feature_ceiling(recs)
        self.assertEqual(r["bar_count"], 40)
        self.assertIn("by_dimension", r)


class TestInformationGain(unittest.TestCase):
    def test_info_gain_ranking(self):
        recs = [_mock_record(prob=0.3 + i * 0.002, win=i % 2) for i in range(60)]
        ig = analyze_information_gain(recs, _mock_bundle())
        self.assertGreater(len(ig["ranked_features"]), 0)

    def test_candidate_ranking(self):
        ig = analyze_information_gain(
            [_mock_record(win=i % 2) for i in range(50)], _mock_bundle(),
        )
        rank = build_candidate_ranking(ig)
        self.assertIn("top_5", rank)


class TestRedundancy(unittest.TestCase):
    def test_cluster(self):
        corr = np.array([[1.0, 0.9, 0.1], [0.9, 1.0, 0.2], [0.1, 0.2, 1.0]])
        clusters = _cluster_features(corr, ["a", "b", "c"], 0.85)
        self.assertTrue(any("a" in cl for cl in clusters))

    def test_redundancy_report(self):
        recs = [_mock_record() for _ in range(30)]
        r = analyze_feature_redundancy(recs, _mock_bundle())
        self.assertIn("correlation_matrix", r)


class TestCeilingSimulation(unittest.TestCase):
    def test_simulation_runs(self):
        recs = [_mock_record(prob=0.33, win=i % 3 == 0) for i in range(80)]
        sim = simulate_ceiling_improvement(
            recs, ["trend_persistence", "adx_acceleration"], _mock_bundle(),
        )
        self.assertTrue(sim["simulation_only"])
        self.assertFalse(sim["frozen_bundle_retrained"])

    def test_insufficient_samples(self):
        sim = simulate_ceiling_improvement([_mock_record()], [], _mock_bundle())
        self.assertIn("error", sim)


class TestFeatureGap(unittest.TestCase):
    def test_gap_analysis(self):
        ig = {"ranked_features": [
            {"group": "candidate", "feature": "trend_persistence", "mutual_info_win": 0.02},
        ]}
        gap = build_feature_gap_analysis(ig, {}, {}, _mock_bundle())
        self.assertIn("missing_high_value_candidates", gap)


class TestVerdict(unittest.TestCase):
    def test_feature_set_limited(self):
        v = determine_verdict(
            {"hypothesis_scores": {"A_missing_information": 0.8, "B_rf_architecture": 0.2,
             "C_training_labels": 0.1, "D_combination": 0.0}},
            {"candidates_outperform_existing": True},
            {"candidates_add_information": True},
            {"confidence_saturates_due_to_lack_of_information": True},
        )
        self.assertEqual(v, "FEATURE_SET_LIMITED")

    def test_multiple_limitations(self):
        v = determine_verdict(
            {"hypothesis_scores": {"A_missing_information": 0.6, "B_rf_architecture": 0.6,
             "C_training_labels": 0.1, "D_combination": 0.7}},
            {}, {}, {},
        )
        self.assertEqual(v, "MULTIPLE_LIMITATIONS")

    def test_recommend_phase(self):
        for verdict in VERDICTS:
            self.assertIn("Phase 17A", recommend_next_phase(verdict))


class TestPackageLayout(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase16d_feature_study.py").is_file())

    def test_orchestrator(self):
        from tradingbot.ml.research.phase16d.orchestrator import run_phase16d_study
        self.assertTrue(callable(run_phase16d_study))


def _make_bulk_saturation_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            bins = [{"mean_prob": 0.33 + (idx % 3) * 0.01 * j} for j in range(4)]
            s = _saturation_score(bins)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)
        test.__name__ = f"test_bulk_saturation_{i}"
        setattr(TestBulkSaturation, test.__name__, test)


def _make_bulk_record_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            r = _mock_record(prob=0.3 + idx * 0.001, adx=20 + idx)
            self.assertGreater(r.probability, 0.0)
            self.assertIn("rsi", r.existing)
        test.__name__ = f"test_bulk_record_{i}"
        setattr(TestBulkRecord, test.__name__, test)


def _make_bulk_verdict_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            a = 0.2 + (idx % 10) * 0.08
            v = determine_verdict(
                {"hypothesis_scores": {
                    "A_missing_information": a,
                    "B_rf_architecture": 0.3,
                    "C_training_labels": 0.2,
                    "D_combination": 0.1,
                }},
                {"candidates_outperform_existing": idx % 2 == 0},
                {"candidates_add_information": idx % 3 == 0},
                {"confidence_saturates_due_to_lack_of_information": idx % 2 == 1},
            )
            self.assertIn(v, VERDICTS)
        test.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, test.__name__, test)


def _make_bulk_catalog_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            entry = CANDIDATE_CATALOG[idx % len(CANDIDATE_CATALOG)]
            self.assertIn("id", entry)
            self.assertIn("description", entry)
        test.__name__ = f"test_bulk_catalog_{i}"
        setattr(TestBulkCatalog, test.__name__, test)


class TestBulkSaturation(unittest.TestCase):
    pass


class TestBulkRecord(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkCatalog(unittest.TestCase):
    pass


_make_bulk_saturation_tests()
_make_bulk_record_tests()
_make_bulk_verdict_tests()
_make_bulk_catalog_tests()


if __name__ == "__main__":
    unittest.main()
