"""Phase 14.8 — stress validation tests."""

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
from tradingbot.ml.research.phase14_8.confidence_audit import audit_confidence
from tradingbot.ml.research.phase14_8.config import (
    EXPECTED_FINGERPRINT,
    MARKET_SCENARIOS,
    MONTE_CARLO_SIMS,
    VALIDATION_PERIODS,
    WF_YEARS,
)
from tradingbot.ml.research.phase14_8.drawdown_analyzer import analyze_drawdown
from tradingbot.ml.research.phase14_8.monte_carlo_extended import run_monte_carlo_extended
from tradingbot.ml.research.phase14_8.multi_period_validator import slice_candles
from tradingbot.ml.research.phase14_8.orchestrator import run_phase14_8_stress_validation
from tradingbot.ml.research.phase14_8.range_engine_audit import audit_range_engine
from tradingbot.ml.research.phase14_8.regime_stress_test import run_regime_stress_test
from tradingbot.ml.research.phase14_8.report_generator import build_final_report
from tradingbot.ml.research.phase14_8.risk_audit import audit_risk
from tradingbot.ml.research.phase14_8.stress_runner import filter_records_by_scenario, summarize_pipelines
from tradingbot.ml.research.phase14_8.trend_engine_audit import audit_trend_engine
from tradingbot.ml.research.phase14_8.walk_forward_extended import run_walk_forward_extended
from tradingbot.ml.research.phase14_6.calibration_alternatives import build_calibration_method

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase14_8"
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


class TestPhase148StressValidation(unittest.TestCase):
    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_validation_periods(self):
        self.assertEqual(VALIDATION_PERIODS, (90, 180, 365))

    def test_market_scenarios_count(self):
        self.assertEqual(len(MARKET_SCENARIOS), 6)

    def test_monte_carlo_sims(self):
        self.assertEqual(MONTE_CARLO_SIMS, 5000)

    def test_wf_years(self):
        self.assertEqual(len(WF_YEARS), 6)

    def test_slice_candles(self):
        c = slice_candles(_candles(600), days=30)
        self.assertGreater(len(c), 0)

    def test_filter_normal_scenario(self):
        recs = [{"timestamp": "t", "regime": "TREND"}]
        self.assertEqual(len(filter_records_by_scenario(recs, "normal")), 1)

    def test_filter_trend_scenario(self):
        recs = [
            {"timestamp": "t1", "regime": "TREND"},
            {"timestamp": "t2", "regime": "RANGE"},
        ]
        out = filter_records_by_scenario(recs, "trend_market")
        self.assertEqual(len(out), 1)

    def test_summarize_pipelines(self):
        rec = [{"allowed": True, "r_multiple": 1.0, "confidence": 0.6, "risk_percent": 0.2, "quality_score": 0.7}]
        out = summarize_pipelines(rec, rec, rec)
        self.assertIn("phase14_full", out)

    def test_drawdown_analyzer(self):
        recs = [{"allowed": True, "r_multiple": 1.0}, {"allowed": True, "r_multiple": -0.5}]
        dd = analyze_drawdown(recs)
        self.assertGreaterEqual(dd["max_drawdown"], 0)

    def test_risk_audit_passes(self):
        recs = [
            {"allowed": True, "raw_signal": "BUY", "risk_percent": 0.25},
            {"allowed": False, "raw_signal": "BUY", "risk_percent": 0.1, "block_reason": "risk"},
        ]
        out = audit_risk(recs)
        self.assertTrue(out["passes"])

    def test_risk_audit_fails_exceeds_cap(self):
        recs = [{"allowed": True, "raw_signal": "BUY", "risk_percent": 0.6}]
        out = audit_risk(recs)
        self.assertFalse(out["passes"])

    def test_confidence_audit(self):
        recs = [{"allowed": True, "raw_signal": "BUY", "confidence": 0.7, "raw_confidence": 0.5}]
        out = audit_confidence(recs)
        self.assertIn("accepted_confidence", out)

    def test_trend_engine_audit(self):
        recs = [{"allowed": True, "engine": "trend_rf_v40", "r_multiple": 1.0}]
        out = audit_trend_engine(recs)
        self.assertEqual(out["engine"], "trend_rf_v40")

    def test_range_engine_audit(self):
        recs = [{"allowed": True, "engine": "phase9_9", "r_multiple": 0.5}]
        out = audit_range_engine(recs)
        self.assertEqual(out["engine"], "phase9_9")

    def test_regime_stress_test(self):
        recs = [
            {"allowed": True, "regime": "TREND", "r_multiple": 1.0, "engine": "trend_rf_v40"},
            {"allowed": True, "regime": "RANGE", "r_multiple": -1.0, "engine": "phase9_9"},
        ]
        out = run_regime_stress_test(recs)
        self.assertIn("regimes", out)

    def test_monte_carlo_extended_reproducible(self):
        recs = [{"allowed": True, "r_multiple": 0.5}] * 80
        a = run_monte_carlo_extended(recs, simulations=50, seed=3)
        b = run_monte_carlo_extended(recs, simulations=50, seed=3)
        self.assertEqual(a["pf_distribution"]["mean"], b["pf_distribution"]["mean"])

    def test_monte_carlo_extended_ci(self):
        recs = [{"allowed": True, "r_multiple": 1.0}] * 40
        out = run_monte_carlo_extended(recs, simulations=100, seed=1)
        self.assertIn("expectancy_ci", out)

    def test_walk_forward_no_shuffle(self):
        c = _candles(800)
        method = build_calibration_method("platt")
        wf = run_walk_forward_extended(c, None, method, confidence_threshold=0.3, quick=True)
        self.assertFalse(wf["shuffle"])

    def test_build_final_report_pass(self):
        final = build_final_report(
            multi_period={"positive_periods": 3},
            regime_stress={"collapse_check": {"unrealistic_dominance": False}},
            risk_audit={"passes": True},
            walk_forward={"robustness_score": 0.5, "overfit_detected": False},
            monte_carlo={"profitable_pct": 0.96},
            fingerprint_unchanged=True,
            full_metrics={"expectancy": 0.5, "profit_factor": 1.5},
        )
        self.assertIn("PHASE_14_8_STATUS", final)

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

    def test_risk_no_negative(self):
        out = audit_risk([{"raw_signal": "BUY", "risk_percent": -0.1}])
        self.assertFalse(out["passes"])

    def test_risk_invalid_percentage(self):
        out = audit_risk([{"raw_signal": "BUY", "risk_percent": 1.5}])
        self.assertFalse(out["passes"])

    def test_filter_high_vol_scenario(self):
        recs = [{"timestamp": "2022-01-01", "regime": "TREND"}]
        meta = {"2022-01-01": 75.0}
        out = filter_records_by_scenario(recs, "high_volatility", meta)
        self.assertEqual(len(out), 1)

    def test_filter_low_vol_scenario(self):
        recs = [{"timestamp": "2022-01-01", "regime": "RANGE"}]
        meta = {"2022-01-01": 20.0}
        out = filter_records_by_scenario(recs, "low_volatility", meta)
        self.assertEqual(len(out), 1)

    def test_monte_carlo_no_trades(self):
        out = run_monte_carlo_extended([], simulations=10, seed=1)
        self.assertFalse(out["passes_gate"])

    def test_trend_contribution_pct(self):
        recs = [
            {"allowed": True, "engine": "trend_rf_v40", "r_multiple": 1.0},
            {"allowed": True, "engine": "phase9_9", "r_multiple": 1.0},
        ]
        out = audit_trend_engine(recs)
        self.assertEqual(out["contribution_pct"], 0.5)

    def test_regime_high_vol_no_fake_if_zero(self):
        recs = [{"allowed": True, "regime": "HIGH_VOLATILITY", "r_multiple": 1.0, "engine": "trend_rf_v40"}]
        out = run_regime_stress_test(recs)
        self.assertIn("collapse_check", out)

    def test_orchestrator_quick_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase14_8_stress_validation(
                symbol="XAUUSD", timeframe="M5", days=30, base_dir=tmp, seed=42, quick=True
            )
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertIn("phase14_8_final_report", result.reports)

    def test_report_files_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_8_stress_validation(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            from tradingbot.ml.research.phase14_8.config import phase14_8_reports_dir

            out = phase14_8_reports_dir(tmp)
            self.assertTrue((out / "phase14_8_final_report.json").is_file())
            self.assertTrue((out / "stress_results.json").is_file())
            self.assertTrue((out / "risk_audit.json").is_file())

    def test_chronological_wf_flag(self):
        method = build_calibration_method("platt")
        wf = run_walk_forward_extended(_candles(800), None, method, confidence_threshold=0.3, quick=True)
        self.assertTrue(wf["chronological"])

    def test_drawdown_empty(self):
        self.assertEqual(analyze_drawdown([])["max_drawdown"], 0.0)

    def test_confidence_empty_signals(self):
        out = audit_confidence([])
        self.assertEqual(out["signal_confidence"]["count"], 0)

    def test_range_baseline_trades(self):
        base = [{"allowed": True, "engine": "phase9_9", "r_multiple": 1.0}]
        out = audit_range_engine([], baseline_records=base)
        self.assertEqual(out["baseline_trades"], 1)


if __name__ == "__main__":
    unittest.main()
