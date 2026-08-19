"""Phase 14.7 — end-to-end pipeline validation tests."""

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
from tradingbot.ml.research.phase14_6.calibration_alternatives import build_calibration_method
from tradingbot.ml.research.phase14_7.baseline_runner import run_baseline_pipeline
from tradingbot.ml.research.phase14_7.calibration_adapter import build_calibrated_adapter, load_recovered_calibration
from tradingbot.ml.research.phase14_7.config import (
    EXPECTED_FINGERPRINT,
    MIN_TRADE_FLOOR,
    PIPELINE_BASELINE,
    PIPELINE_FULL,
    PIPELINE_ROUTER,
    WF_YEARS,
    load_phase14_6_policy,
)
from tradingbot.ml.research.phase14_7.engine_contribution import analyze_engine_contribution
from tradingbot.ml.research.phase14_7.monte_carlo_validator import run_monte_carlo_validation
from tradingbot.ml.research.phase14_7.orchestrator import run_phase14_7_validation
from tradingbot.ml.research.phase14_7.performance_analyzer import analyze_performance, compare_pipelines, sharpe_like_stability
from tradingbot.ml.research.phase14_7.pipeline_runner import run_full_pipeline
from tradingbot.ml.research.phase14_7.quality_adapter import build_quality_adapter
from tradingbot.ml.research.phase14_7.regime_analyzer import analyze_regimes, detect_regime_collapse
from tradingbot.ml.research.phase14_7.report_generator import build_final_report
from tradingbot.ml.research.phase14_7.risk_adapter import build_risk_adapter
from tradingbot.ml.research.phase14_7.router_runner import run_router_pipeline
from tradingbot.ml.research.phase14_7.trade_tracker import build_trade_record, count_by_key
from tradingbot.ml.research.phase14_7.walk_forward_validator import run_walk_forward_validation

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase14_7"
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


class TestPhase147PipelineValidation(unittest.TestCase):
    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_pipeline_constants(self):
        self.assertEqual(PIPELINE_BASELINE, "phase9_9_baseline")
        self.assertEqual(PIPELINE_ROUTER, "phase13_10_router")
        self.assertEqual(PIPELINE_FULL, "phase14_full")

    def test_min_trade_floor(self):
        self.assertEqual(MIN_TRADE_FLOOR, 300)

    def test_wf_years(self):
        self.assertEqual(len(WF_YEARS), 6)

    def test_load_phase14_6_policy_defaults(self):
        policy = load_phase14_6_policy("/nonexistent")
        self.assertEqual(policy["calibration_method"], "platt")

    def test_build_trade_record(self):
        rec = build_trade_record(
            timestamp="2022-01-01", year=2022, pipeline="test", raw_signal="BUY",
            allowed=True, block_reason=None, engine="phase9_9", regime="RANGE", confidence=0.6,
        )
        self.assertTrue(rec["allowed"])

    def test_sharpe_like_stability(self):
        self.assertGreater(sharpe_like_stability([1.0, 0.5, 1.2]), 0)

    def test_analyze_performance(self):
        records = [{"allowed": True, "r_multiple": 1.0, "confidence": 0.6, "risk_percent": 0.2, "quality_score": 0.7}]
        m = analyze_performance(records)
        self.assertEqual(m["trades"], 1)

    def test_compare_pipelines(self):
        out = compare_pipelines({
            "phase9_9_baseline": {"profit_factor": 1.0, "expectancy": 0.1, "effective_trades_est": 100},
            "phase13_10_router": {"profit_factor": 1.2},
            "phase14_full": {"profit_factor": 1.5, "expectancy": 0.3, "effective_trades_est": 400},
        })
        self.assertTrue(out["full_beats_baseline"])

    def test_analyze_regimes(self):
        records = [
            {"regime": "RANGE", "allowed": True, "r_multiple": 1.0},
            {"regime": "TREND", "allowed": True, "r_multiple": -1.0},
        ]
        out = analyze_regimes(records)
        self.assertIn("RANGE", out["regimes"])

    def test_detect_regime_collapse(self):
        out = detect_regime_collapse(
            {"total_accepted": 10, "regimes": {"HIGH_VOLATILITY": {"contribution_pct": 0.9}}},
            max_dominance=0.85,
        )
        self.assertTrue(out["unrealistic_dominance"])

    def test_engine_contribution(self):
        base = [{"allowed": True, "engine": "phase9_9", "r_multiple": 1.0}]
        router = [
            {"allowed": True, "engine": "phase9_9", "r_multiple": 1.0, "raw_signal": "BUY"},
            {"allowed": True, "engine": "trend_rf_v40", "r_multiple": 0.5, "raw_signal": "BUY"},
        ]
        full = [
            {"allowed": False, "engine": "phase9_9", "raw_signal": "BUY", "block_reason": "confidence"},
            {"allowed": True, "engine": "trend_rf_v40", "r_multiple": 1.0, "raw_signal": "BUY"},
        ]
        out = analyze_engine_contribution(base, router, full)
        self.assertIn("phase9_9", out)

    def test_count_by_key(self):
        self.assertEqual(count_by_key([{"engine": "a"}, {"engine": "a"}], "engine")["a"], 2)

    def test_build_calibrated_adapter(self):
        method = build_calibration_method("platt")
        adapter = build_calibrated_adapter(method, confidence_threshold=0.3)
        self.assertIsNotNone(adapter.calibration_method)

    def test_build_risk_adapter(self):
        method = build_calibration_method("phase14_2a")
        decision = build_calibrated_adapter(method, confidence_threshold=0.55)
        risk = build_risk_adapter(decision)
        self.assertIsNotNone(risk.risk_engine)

    def test_build_quality_adapter(self):
        method = build_calibration_method("phase14_2a")
        decision = build_calibrated_adapter(method, confidence_threshold=0.55)
        quality = build_quality_adapter(build_risk_adapter(decision))
        self.assertIsNotNone(quality.quality_engine)

    def test_monte_carlo_reproducible(self):
        records = [{"allowed": True, "r_multiple": 0.5}] * 80
        a = run_monte_carlo_validation(records, simulations=50, seed=7)
        b = run_monte_carlo_validation(records, simulations=50, seed=7)
        self.assertEqual(a["pf_distribution"]["mean"], b["pf_distribution"]["mean"])

    def test_monte_carlo_no_trades(self):
        mc = run_monte_carlo_validation([], simulations=10, seed=1)
        self.assertFalse(mc["passes_gate"])

    def test_walk_forward_no_shuffle(self):
        c = _candles(800)
        method = build_calibration_method("platt")
        wf = run_walk_forward_validation(c, None, method, confidence_threshold=0.3, quick=True)
        self.assertFalse(wf["shuffle"])

    def test_build_final_report(self):
        final = build_final_report(
            comparison={"full_beats_baseline": True, "baseline_pf": 1.0, "pf_improvement_vs_baseline": 0.2},
            full_metrics={"effective_trades_est": 400, "profit_factor": 1.5, "expectancy": 0.3},
            regime_check={"collapsed": False, "unrealistic_dominance": False},
            walk_forward={"robustness_score": 0.5},
            monte_carlo={"profitable_pct": 0.96},
            fingerprint_unchanged=True,
            calibration_policy={"calibration_method": "platt"},
        )
        self.assertIn("PHASE_14_7_STATUS", final)

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

    def test_no_riskgate_modification(self):
        for py in PKG.rglob("*.py"):
            self.assertNotIn("riskgate.", py.read_text(encoding="utf-8").lower())

    def test_baseline_runner_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            records = run_baseline_pipeline(candles, dataset, stride=10)
            self.assertTrue(all(r["pipeline"] == PIPELINE_BASELINE for r in records))

    def test_router_runner_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            records = run_router_pipeline(candles, dataset, stride=10)
            self.assertTrue(all(r["pipeline"] == PIPELINE_ROUTER for r in records))

    def test_full_pipeline_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            method, policy = load_recovered_calibration(candles, dataset, base_dir=tmp, stride=10)
            records = run_full_pipeline(
                candles, dataset, method,
                confidence_threshold=policy["confidence_threshold"], stride=10,
            )
            self.assertTrue(all(r["pipeline"] == PIPELINE_FULL for r in records))

    def test_calibration_bounds(self):
        method = build_calibration_method("percentile")
        raw = RawConfidence(
            raw_value=0.5, engine="phase9_9", regime="RANGE", model_probability=0.6,
            regime_strength=0.7, market_quality=0.8, session="london", volatility=40.0,
        )
        from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationSample
        method.fit([CalibrationSample(raw=raw, outcome=1)])
        out = method.calibrate(raw)
        self.assertLessEqual(out.calibrated_value, 1.0)
        self.assertGreaterEqual(out.calibrated_value, 0.0)

    def test_orchestrator_quick_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase14_7_validation(
                symbol="XAUUSD", timeframe="M5", days=30, base_dir=tmp, seed=42, quick=True
            )
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertIn("phase14_7_final_report", result.reports)

    def test_report_files_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_7_validation(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            from tradingbot.ml.research.phase14_7.config import phase14_7_reports_dir

            out = phase14_7_reports_dir(tmp)
            self.assertTrue((out / "phase14_7_final_report.json").is_file())
            self.assertTrue((out / "engine_contribution.json").is_file())
            self.assertTrue((out / "baseline_comparison.json").is_file())

    def test_chronological_wf_years(self):
        self.assertEqual(WF_YEARS, (2021, 2022, 2023, 2024, 2025, 2026))


if __name__ == "__main__":
    unittest.main()
