"""Phase 14.6 — calibration recovery tests."""

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

from tradingbot.ml.confidence_engine.calibration_types import RawConfidence
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase14_6.calibration_alternatives import (
    PercentileCalibration,
    Phase14_2ACalibration,
    ProbabilityCalibration,
    build_calibration_method,
    compare_calibration_methods,
)
from tradingbot.ml.research.phase14_6.calibration_audit import attribute_compression, run_calibration_audit
from tradingbot.ml.research.phase14_6.config import (
    CALIBRATION_METHODS,
    CONFIDENCE_BUCKETS,
    EXPECTED_FINGERPRINT,
    MIN_TRADE_FLOOR,
    THRESHOLD_GRID,
    WF_YEARS,
)
from tradingbot.ml.research.phase14_6.confidence_distribution import compression_resolved, distribution_stats
from tradingbot.ml.research.phase14_6.label_alignment import analyze_label_alignment, bucket_for_confidence
from tradingbot.ml.research.phase14_6.monte_carlo_validator import run_monte_carlo_validation
from tradingbot.ml.research.phase14_6.orchestrator import run_phase14_6_recovery
from tradingbot.ml.research.phase14_6.report_generator import build_final_report
from tradingbot.ml.research.phase14_6.threshold_search import composite_threshold_score
from tradingbot.ml.research.phase14_6.walk_forward_validator import run_walk_forward_validation

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase14_6"
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


def _raw(engine: str = "phase9_9", value: float = 0.4) -> RawConfidence:
    return RawConfidence(
        raw_value=value,
        engine=engine,
        regime="RANGE" if engine == "phase9_9" else "TREND",
        model_probability=0.6,
        regime_strength=0.7,
        market_quality=0.8,
        session="london",
        volatility=40.0,
        engine_signal="BUY",
    )


class TestPhase146CalibrationRecovery(unittest.TestCase):
    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_threshold_grid(self):
        self.assertEqual(len(THRESHOLD_GRID), 6)

    def test_calibration_methods(self):
        self.assertIn("percentile", CALIBRATION_METHODS)

    def test_min_trade_floor(self):
        self.assertEqual(MIN_TRADE_FLOOR, 300)

    def test_wf_years(self):
        self.assertEqual(WF_YEARS[0], 2021)

    def test_confidence_buckets(self):
        self.assertEqual(len(CONFIDENCE_BUCKETS), 5)

    def test_distribution_stats(self):
        stats = distribution_stats([0.1, 0.2, 0.3, 0.8, 0.9])
        self.assertGreater(stats["std"], 0)

    def test_compression_resolved(self):
        self.assertTrue(compression_resolved({"spread_p90_p10": 0.3, "std": 0.05}, min_spread=0.25, min_std=0.12))

    def test_bucket_for_confidence(self):
        self.assertEqual(bucket_for_confidence(0.15), "0.0-0.2")

    def test_percentile_calibration_bounds(self):
        cal = PercentileCalibration()
        cal.fit([type("S", (), {"raw": _raw(value=v)})() for v in [0.1, 0.2, 0.5, 0.8]])
        out = cal.calibrate(_raw(value=0.8))
        self.assertGreaterEqual(out.calibrated_value, 0.0)
        self.assertLessEqual(out.calibrated_value, 1.0)

    def test_phase14_2a_benchmark(self):
        out = Phase14_2ACalibration().calibrate(_raw())
        self.assertGreaterEqual(out.calibrated_value, 0.0)

    def test_probability_calibration_bounds(self):
        from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationSample

        cal = ProbabilityCalibration("platt")
        samples = [CalibrationSample(raw=_raw(value=i / 20), outcome=i % 2) for i in range(40)]
        cal.fit(samples)
        out = cal.calibrate(_raw(value=0.5))
        self.assertLessEqual(out.calibrated_value, 1.0)

    def test_build_calibration_method(self):
        self.assertEqual(build_calibration_method("percentile").methods["phase9_9"].name, "percentile")

    def test_compare_methods_chronological(self):
        from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationSample

        samples = [CalibrationSample(raw=_raw(value=i / 10), outcome=i % 2) for i in range(20)]
        out = compare_calibration_methods(samples, methods=("phase14_2a", "percentile"))
        self.assertFalse(out["shuffle"])

    def test_attribute_compression(self):
        recs = [
            {
                "phase14_1_raw": 0.4,
                "calibrated_confidence": 0.1,
                "regime": "RANGE",
                "session": "london",
                "decomposition": {"min_raw_blocked": False, "extreme_vol_blocked": False, "steps": []},
            }
        ]
        out = attribute_compression(recs)
        self.assertIn("ranked_adjustments", out)

    def test_label_alignment(self):
        records = [
            {"raw_signal": "BUY", "confidence": 0.7, "r_multiple": 1.0},
            {"raw_signal": "SELL", "confidence": 0.3, "r_multiple": -1.0},
        ]
        out = analyze_label_alignment(records)
        self.assertIn("buckets", out)

    def test_composite_threshold_penalizes_low_trades(self):
        self.assertEqual(composite_threshold_score({"effective_trades_est": 50}), 0.0)

    def test_monte_carlo_reproducible(self):
        records = [{"allowed": True, "r_multiple": 0.5}] * 80
        a = run_monte_carlo_validation(records, simulations=50, seed=7)
        b = run_monte_carlo_validation(records, simulations=50, seed=7)
        self.assertEqual(a["pf_distribution"]["mean"], b["pf_distribution"]["mean"])

    def test_walk_forward_no_shuffle(self):
        c = _candles(800)
        method = build_calibration_method("phase14_2a")
        wf = run_walk_forward_validation(c, None, method, confidence_threshold=0.45, quick=True)
        self.assertFalse(wf["shuffle"])

    def test_build_final_report(self):
        final = build_final_report(
            audit={},
            calibration_comparison={"methods": [{"compression_resolved": True}]},
            bucket_analysis={},
            threshold_search={},
            walk_forward={"robustness_score": 0.5},
            monte_carlo={"profitable_pct": 0.96},
            fingerprint_unchanged=True,
            best_method="percentile",
            best_threshold=0.4,
            best_metrics={"effective_trades_est": 400, "profit_factor": 1.2, "expectancy": 0.3},
        )
        self.assertIn("PHASE_14_6_STATUS", final)

    def test_no_forbidden_imports(self):
        for py in PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_order_send_strings(self):
        for py in PKG.rglob("*.py"):
            self.assertNotIn("order_send", py.read_text(encoding="utf-8"))

    def test_engine_separation(self):
        method = build_calibration_method("percentile")
        self.assertIn("phase9_9", method.methods)
        self.assertIn("trend_rf_v40", method.methods)

    def test_calibration_audit_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            audit = run_calibration_audit(candles, dataset, stride=10)
            self.assertIn("compression_attribution", audit)

    def test_orchestrator_quick_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase14_6_recovery(
                symbol="XAUUSD", timeframe="M5", days=30, base_dir=tmp, seed=42, quick=True
            )
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertIn("phase14_6_final_report", result.reports)

    def test_report_files_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_6_recovery(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            from tradingbot.ml.research.phase14_6.config import phase14_6_reports_dir

            out = phase14_6_reports_dir(tmp)
            self.assertTrue((out / "phase14_6_final_report.json").is_file())
            self.assertTrue((out / "confidence_audit.json").is_file())


if __name__ == "__main__":
    unittest.main()
