"""Phase 14.10 — walk-forward stability recovery tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase14_10.adaptive_regime_policy import research_regime_policy
from tradingbot.ml.research.phase14_10.adaptive_threshold_research import research_adaptive_threshold
from tradingbot.ml.research.phase14_10.config import (
    BASELINE_THRESHOLD,
    EXPECTED_FINGERPRINT,
    MIN_WF_ROBUSTNESS,
    THRESHOLD_GRID,
    WF_YEARS,
    load_calibration_policy,
    phase14_10_reports_dir,
    regime_pct_from_records,
    slice_year,
)
from tradingbot.ml.research.phase14_10.montecarlo_per_year import run_montecarlo_per_year
from tradingbot.ml.research.phase14_10.orchestrator import run_phase14_10_stability
from tradingbot.ml.research.phase14_10.regime_transition_analysis import analyze_regime_transitions
from tradingbot.ml.research.phase14_10.report_generator import build_final_report, build_recommendations
from tradingbot.ml.research.phase14_10.robustness_rebuilder import recompute_robustness
from tradingbot.ml.research.phase14_10.yearly_calibration_analysis import analyze_calibration_stability
from tradingbot.ml.research.phase14_10.yearly_confidence_distribution import analyze_confidence_distribution
from tradingbot.ml.research.phase14_10.yearly_feature_drift import analyze_feature_drift
from tradingbot.ml.research.phase14_10.yearly_performance import compute_yearly_metrics
from tradingbot.ml.research.phase14_10.yearly_regime_distribution import analyze_regime_distribution
from tradingbot.ml.research.phase14_10.yearly_threshold_analysis import analyze_yearly_thresholds
from tradingbot.ml.research.phase14_10.yearly_trade_distribution import analyze_trade_distribution
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase14_10"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")


def _candles(n: int = 600, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2022-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300.0 + rng.normal(0, 0.5, n).cumsum()
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close},
        index=ts,
    )


def _setup(tmp: str) -> None:
    store = DatasetStore(tmp)
    ts = pd.date_range("2022-01-01", periods=500, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    store.store_v2(
        "XAUUSD",
        "M5",
        pd.DataFrame(
            {
                "timestamp": ts,
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "label": [0, 1] * 250,
                "ema50_slope": rng.normal(0, 1, 500).tolist(),
                "candle_direction": rng.normal(0, 1, 500).tolist(),
                "structure_distance": rng.normal(0, 1, 500).tolist(),
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
            }
        ),
    )
    CandleStore(tmp).store("XAUUSD", "M5", _candles(600))


class TestPhase1410Stability(unittest.TestCase):
    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_wf_years(self):
        self.assertEqual(WF_YEARS, (2021, 2022, 2023, 2024, 2025, 2026))

    def test_threshold_grid(self):
        self.assertEqual(THRESHOLD_GRID, (0.25, 0.30, 0.35, 0.40))

    def test_baseline_threshold(self):
        self.assertEqual(BASELINE_THRESHOLD, 0.30)

    def test_min_wf_robustness(self):
        self.assertEqual(MIN_WF_ROBUSTNESS, 0.40)

    def test_load_calibration_policy(self):
        p = load_calibration_policy("/nonexistent")
        self.assertEqual(p["calibration_method"], "platt")

    def test_slice_year(self):
        c = _candles(600)
        ds = pd.DataFrame({"timestamp": c.index, "label": [0] * len(c)})
        yc, yds = slice_year(c, ds, 2022)
        self.assertFalse(yc.empty)

    def test_regime_pct_from_records(self):
        recs = [{"regime": "TREND"}, {"regime": "RANGE"}, {"regime": "TREND"}]
        out = regime_pct_from_records(recs)
        self.assertAlmostEqual(out["TREND"], 2 / 3, places=2)

    def test_robustness_score(self):
        from tradingbot.ml.research.phase14_10.robustness_rebuilder import compute_robustness_score

        self.assertGreater(compute_robustness_score([1.5, 1.6, 1.4]), 0.8)

    def test_feature_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            out = analyze_feature_drift(candles, dataset, years=(2022,))
            self.assertIn("per_year", out)

    def test_regime_distribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            out = analyze_regime_distribution(candles, dataset, years=(2022,))
            self.assertIn("per_year", out)

    def test_yearly_metrics_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            out = compute_yearly_metrics(
                candles, dataset, method, confidence_threshold=0.30,
                stride=20, years=(2022,),
            )
            self.assertIn("per_year", out)

    def test_trade_distribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            out = analyze_trade_distribution(
                candles, dataset, method, confidence_threshold=0.30, stride=20, years=(2022,),
            )
            self.assertIn("per_year", out)

    def test_threshold_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            out = analyze_yearly_thresholds(
                candles, dataset, method, stride=20, years=(2022,), thresholds=(0.30, 0.35),
            )
            self.assertIn("optimal_threshold_per_year", out)

    def test_confidence_distribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            out = analyze_confidence_distribution(
                candles, dataset, method, confidence_threshold=0.30, stride=20, years=(2022,),
            )
            self.assertIn("histogram_calibrated", out["per_year"]["2022"])

    def test_calibration_stability(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            out = analyze_calibration_stability(
                candles, dataset, method, confidence_threshold=0.30, stride=20, years=(2022,),
            )
            self.assertIn("platt_global_fit", out)

    def test_transition_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            out = analyze_regime_transitions(
                candles, dataset, method, confidence_threshold=0.30, stride=20, years=(2022,),
            )
            self.assertIn("aggregate_transitions", out)

    def test_adaptive_threshold_research_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            regime = analyze_regime_distribution(candles, dataset, years=(2022,))
            out = research_adaptive_threshold(
                candles, dataset, method, regime, stride=20, years=(2022,),
            )
            self.assertTrue(out["research_only"])

    def test_adaptive_regime_policy_research_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            out = research_regime_policy(
                candles, dataset, method, stride=20, years=(2022,),
            )
            self.assertTrue(out["research_only"])

    def test_montecarlo_per_year_deterministic(self):
        recs = [{"allowed": True, "r_multiple": 0.5}] * 40
        from tradingbot.ml.research.phase14_8.monte_carlo_extended import run_monte_carlo_extended

        a = run_monte_carlo_extended(recs, simulations=50, seed=99)
        b = run_monte_carlo_extended(recs, simulations=50, seed=99)
        self.assertEqual(a["pf_distribution"]["mean"], b["pf_distribution"]["mean"])

    def test_montecarlo_per_year_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            out = run_montecarlo_per_year(
                candles, dataset, method, confidence_threshold=0.30,
                stride=20, simulations=50, years=(2022,),
            )
            self.assertIn("per_year", out)

    def test_recompute_robustness(self):
        ym = {"per_year": {"2022": {"profit_factor": 2.0, "skipped": False}}}
        at = {"per_year": {"2022": {"adaptive_pf": 2.1, "skipped": False}}}
        ar = {"per_year": {"2022": {"regime_policy_pf": 1.9, "skipped": False}}}
        out = recompute_robustness(ym, at, ar, baseline_robustness=0.17)
        self.assertIn("best_robustness", out)

    def test_build_recommendations(self):
        out = build_recommendations(
            yearly_metrics={"per_year": {}},
            feature_drift={"most_shifted_features": ["adx"]},
            regime_distribution={"regime_shift_summary": {"trend_pct_delta_first_to_last": 0.2}},
            confidence_distribution={"year_comparison": {"confidence_delta": 0.1}},
            calibration_stability={"yearly_calibration_unstable": True, "label_distribution": {}},
            threshold_analysis={"mean_threshold_spread_pf": 0.8},
            adaptive_threshold={"improves_stability": True, "rule": "test"},
            adaptive_regime_policy={"policy_mean_pf": 1.0, "policy": {}},
            transition_analysis={"worst_transition": {"name": "TREND->RANGE"}},
            robustness_recovery={"improvement_vs_baseline": 0.05, "adaptive_threshold_robustness": 0.3},
        )
        self.assertIn("root_cause_ranking", out)

    def test_build_final_report(self):
        final = build_final_report(
            yearly_metrics={"per_year": {"2022": {"profit_factor": 2.0, "trades": 10}}},
            feature_drift={},
            regime_distribution={"regime_shift_summary": {}},
            confidence_distribution={},
            calibration_stability={},
            threshold_analysis={},
            adaptive_threshold={},
            adaptive_regime_policy={},
            transition_analysis={},
            montecarlo_yearly={"years_passing_mc": 1, "active_years": 1},
            robustness_recovery={"best_robustness": 0.2, "static_recomputed": 0.17, "best_research_variant": "static"},
            recommendations={"root_cause_ranking": [{"cause": "test"}], "recommendations": [], "primary_recommendation": "keep_static"},
            fingerprint_unchanged=True,
        )
        self.assertIn("PHASE_14_10_STATUS", final)

    def test_no_forbidden_imports(self):
        for py in PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_order_send(self):
        for py in PKG.rglob("*.py"):
            self.assertNotIn("order_send", py.read_text(encoding="utf-8"))

    def test_no_riskgate_modification(self):
        for py in PKG.rglob("*.py"):
            self.assertNotIn("riskgate.", py.read_text(encoding="utf-8").lower())

    def test_fingerprint_unchanged_after_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            store = DatasetStore(tmp)
            before = dataset_content_fingerprint(store.load_v2("XAUUSD", "M5"))
            run_phase14_10_stability(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            after = dataset_content_fingerprint(store.load_v2("XAUUSD", "M5"))
            self.assertEqual(before, after)

    def test_orchestrator_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase14_10_stability(
                symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, seed=42, quick=True,
            )
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))

    def test_report_files_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_10_stability(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            out = phase14_10_reports_dir(tmp)
            self.assertTrue((out / "yearly_metrics.json").is_file())
            self.assertTrue((out / "feature_drift.json").is_file())
            self.assertTrue((out / "final_phase14_10_report.json").is_file())
            self.assertTrue((out / "recommendations.json").is_file())

    def test_final_report_has_root_causes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_10_stability(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            data = json.loads((phase14_10_reports_dir(tmp) / "final_phase14_10_report.json").read_text())
            self.assertIn("root_cause_ranking", data)

    def test_adaptive_threshold_json_research_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_10_stability(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            data = json.loads((phase14_10_reports_dir(tmp) / "adaptive_threshold.json").read_text())
            self.assertTrue(data.get("research_only"))

    def test_walk_forward_chronological_years(self):
        self.assertEqual(list(WF_YEARS), sorted(WF_YEARS))

    def test_calibration_unchanged_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            m1, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            m2, _ = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=20)
            self.assertEqual(type(m1).__name__, type(m2).__name__)


if __name__ == "__main__":
    unittest.main()
