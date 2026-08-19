"""Phase 14.9 — multi-regime stability tests."""

from __future__ import annotations

import ast
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
from tradingbot.ml.research.phase14_9.adaptive_router import run_adaptive_router_pipeline
from tradingbot.ml.research.phase14_9.config import (
    EXPECTED_FINGERPRINT,
    MIN_PF,
    MIN_TRADE_FLOOR,
    MONTE_CARLO_SIMS,
    VALIDATION_PERIODS,
    load_calibration_policy,
)
from tradingbot.ml.research.phase14_9.dynamic_engine_weight import compute_engine_weights, compute_range_weight, compute_trend_weight
from tradingbot.ml.research.phase14_9.orchestrator import run_phase14_9_stability
from tradingbot.ml.research.phase14_9.range_engine_analysis import analyze_range_engine
from tradingbot.ml.research.phase14_9.regime_performance_audit import audit_regime_performance
from tradingbot.ml.research.phase14_9.report_generator import build_final_report
from tradingbot.ml.research.phase14_9.robustness_validator import run_monte_carlo, validate_robustness
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase14_9"
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


class TestPhase149Stability(unittest.TestCase):
    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_validation_periods(self):
        self.assertEqual(VALIDATION_PERIODS, (90, 180, 365))

    def test_min_pf_threshold(self):
        self.assertEqual(MIN_PF, 1.2)

    def test_min_trade_floor(self):
        self.assertEqual(MIN_TRADE_FLOOR, 300)

    def test_monte_carlo_sims(self):
        self.assertEqual(MONTE_CARLO_SIMS, 5000)

    def test_load_calibration_policy(self):
        p = load_calibration_policy("/nonexistent")
        self.assertEqual(p["calibration_method"], "platt")

    def test_trend_weight_bounds(self):
        row = pd.Series({"adx": 30, "ema50_slope": 0.2, "atr_percentile": 50})
        w, _ = compute_trend_weight(row, regime="TREND")
        self.assertLessEqual(w, 1.0)

    def test_range_weight_bounds(self):
        row = pd.Series({"adx": 15, "atr_percentile": 25, "structure_distance": 0.5})
        w, _ = compute_range_weight(row, regime="RANGE")
        self.assertGreaterEqual(w, 0.0)

    def test_engine_weights_sum(self):
        row = pd.Series({"adx": 20, "ema50_slope": 0.1, "atr_percentile": 40, "structure_distance": 0.3})
        ew = compute_engine_weights(row, regime="RANGE")
        self.assertAlmostEqual(ew.trend_weight + ew.range_weight, 1.0, places=2)

    def test_engine_weights_trend_regime(self):
        row = pd.Series({"adx": 35, "ema50_slope": 0.3, "atr_percentile": 60})
        ew = compute_engine_weights(row, regime="TREND")
        self.assertEqual(ew.selected_engine(), "trend_rf_v40")

    def test_engine_weights_blocked_regime(self):
        row = pd.Series({"adx": 20})
        ew = compute_engine_weights(row, regime="HIGH_VOLATILITY")
        self.assertIsNone(ew.selected_engine())

    def test_regime_audit(self):
        recs = [
            {"allowed": True, "regime": "TREND", "engine": "trend_rf_v40", "r_multiple": 1.0},
            {"allowed": True, "regime": "RANGE", "engine": "phase9_9", "r_multiple": -0.5},
        ]
        out = audit_regime_performance(recs)
        self.assertIn("per_engine", out)

    def test_range_analysis_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            out = analyze_range_engine(candles, dataset, stride=20)
            self.assertIn("zero_trades_root_causes", out)

    def test_monte_carlo_deterministic(self):
        recs = [{"allowed": True, "r_multiple": 0.5}] * 60
        a = run_monte_carlo(recs, simulations=50, seed=11)
        b = run_monte_carlo(recs, simulations=50, seed=11)
        self.assertEqual(a["pf_distribution"]["mean"], b["pf_distribution"]["mean"])

    def test_validate_robustness_pass(self):
        out = validate_robustness(
            [{"allowed": True, "r_multiple": 1.0}] * 80,
            {"robustness_score": 0.5},
            {"profitable_pct": 0.96},
            {"positive_periods": 3},
            stride=1,
        )
        self.assertIn("checks", out)

    def test_build_final_report(self):
        final = build_final_report(
            regime_audit={"per_engine": {"trend_rf_v40": {"trades": 80, "profit_factor": 2.0, "contribution_pct": 1.0}, "phase9_9": {"trades": 0}}},
            range_analysis={"zero_trades_root_causes": ["low confidence"]},
            trend_stability={"period_dependency_high": False},
            robustness={"passes": True, "checks": {}, "metrics": {}},
            engine_comparison={},
            adaptive_results={"router_behavior": {}},
            fingerprint_unchanged=True,
        )
        self.assertIn("PHASE_14_9_STATUS", final)

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

    def test_adaptive_router_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, policy = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=10)
            recs = run_adaptive_router_pipeline(
                candles, dataset, method,
                confidence_threshold=policy["confidence_threshold"], stride=10,
            )
            self.assertGreater(len(recs), 0)
            self.assertIn("trend_weight", recs[0])

    def test_orchestrator_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase14_9_stability(
                symbol="XAUUSD", timeframe="M5", days=30, base_dir=tmp, seed=42, quick=True
            )
            self.assertIn(result.status, ("READY_FOR_PHASE15", "NEEDS_REVIEW"))
            self.assertIn("final_phase14_9_report", result.reports)

    def test_report_files_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_9_stability(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            from tradingbot.ml.research.phase14_9.config import phase14_9_reports_dir

            out = phase14_9_reports_dir(tmp)
            self.assertTrue((out / "final_phase14_9_report.json").is_file())
            self.assertTrue((out / "regime_breakdown.json").is_file())

    def test_weights_high_adx_favors_trend(self):
        row = pd.Series({"adx": 40, "ema50_slope": 0.35, "atr_percentile": 70})
        tw, _ = compute_trend_weight(row, regime="TREND")
        rw, _ = compute_range_weight(row, regime="TREND")
        self.assertGreaterEqual(tw, rw)

    def test_weights_low_adx_favors_range(self):
        row = pd.Series({"adx": 12, "atr_percentile": 20, "structure_distance": 0.4})
        tw, _ = compute_trend_weight(row, regime="RANGE")
        rw, _ = compute_range_weight(row, regime="RANGE")
        self.assertGreaterEqual(rw, tw)

    def test_regime_dominance_detection(self):
        recs = [{"allowed": True, "regime": "TREND", "engine": "trend_rf_v40", "r_multiple": 1.0}] * 10
        out = audit_regime_performance(recs)
        self.assertEqual(out["regime_dominance"]["dominant_regime"], "TREND")

    def test_monte_carlo_no_trades(self):
        out = run_monte_carlo([], simulations=10, seed=1)
        self.assertFalse(out["passes_gate"])

    def test_explanation_in_final_report(self):
        final = build_final_report(
            regime_audit={"per_engine": {"trend_rf_v40": {}, "phase9_9": {}}},
            range_analysis={},
            trend_stability={},
            robustness={"passes": False, "checks": {}, "metrics": {}},
            engine_comparison={},
            adaptive_results={"router_behavior": {"mean_trend_weight": 0.6}},
            fingerprint_unchanged=True,
        )
        self.assertIn("explanation", final)

    def test_range_selected_engine(self):
        row = pd.Series({"adx": 10, "atr_percentile": 15, "structure_distance": 0.2, "ema50_slope": 0.01})
        ew = compute_engine_weights(row, regime="RANGE")
        self.assertIn(ew.selected_engine(), ("phase9_9", "trend_rf_v40", None))

    def test_regime_audit_empty(self):
        out = audit_regime_performance([])
        self.assertEqual(out["total_accepted"], 0)

    def test_calibration_policy_threshold(self):
        p = load_calibration_policy(None)
        self.assertLessEqual(p["confidence_threshold"], 0.55)


if __name__ == "__main__":
    unittest.main()
