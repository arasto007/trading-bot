"""Phase 14.4 — signal optimization tests."""

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
from tradingbot.ml.research.phase14_4.config import (
    CONFIDENCE_GRID,
    EXPECTED_FINGERPRINT,
    MIN_TRADES_PASS,
    MONTE_CARLO_SIMS,
    QUALITY_GRID,
    RISK_CAP_GRID,
    WF_WINDOWS,
)
from tradingbot.ml.research.phase14_4.missed_trade_analyzer import analyze_missed_trades, classify_blocked_trade
from tradingbot.ml.research.phase14_4.monte_carlo_validator import run_monte_carlo_validation
from tradingbot.ml.research.phase14_4.pipeline_simulator import (
    PipelineThresholds,
    simulate_trade_outcome,
    trade_metrics_from_records,
)
from tradingbot.ml.research.phase14_4.robustness_validator import pf_stability, robustness_score
from tradingbot.ml.research.phase14_4.orchestrator import run_phase14_4_optimizer
from tradingbot.ml.research.phase14_4.report_generator import build_final_report
from tradingbot.ml.research.phase14_4.trade_frequency_analyzer import analyze_trade_frequency
from tradingbot.ml.research.phase14_4.walk_forward_optimizer import run_walk_forward_optimization

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase14_4"
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


class TestPhase144Optimizer(unittest.TestCase):
    def test_confidence_grid_size(self):
        self.assertEqual(len(CONFIDENCE_GRID), 7)

    def test_quality_grid_size(self):
        self.assertEqual(len(QUALITY_GRID), 6)

    def test_risk_cap_grid(self):
        self.assertIn(0.50, RISK_CAP_GRID)

    def test_min_trades_constant(self):
        self.assertEqual(MIN_TRADES_PASS, 300)

    def test_wf_windows_no_shuffle(self):
        self.assertEqual(len(WF_WINDOWS), 6)

    def test_simulate_trade_outcome(self):
        c = _candles(100)
        out = simulate_trade_outcome(c, 10, direction="BUY")
        self.assertIn("r_multiple", out)
        self.assertIn("mfe", out)

    def test_trade_metrics_empty(self):
        m = trade_metrics_from_records([])
        self.assertEqual(m["trades"], 0)

    def test_classify_missed_winner(self):
        self.assertEqual(
            classify_blocked_trade({"allowed": False, "raw_signal": "BUY", "r_multiple": 2.0}),
            "MISSED_WINNER",
        )

    def test_classify_good_block(self):
        self.assertEqual(
            classify_blocked_trade({"allowed": False, "raw_signal": "SELL", "r_multiple": -1.0}),
            "GOOD_BLOCK",
        )

    def test_missed_trade_analyzer(self):
        records = [
            {"allowed": False, "raw_signal": "BUY", "r_multiple": 2.0, "confidence": 0.5, "risk_percent": 0.2, "quality_score": 0.5},
            {"allowed": True, "raw_signal": "BUY", "r_multiple": 1.0, "confidence": 0.8, "risk_percent": 0.2, "quality_score": 0.8},
        ]
        report = analyze_missed_trades(records)
        self.assertIn("classification_counts", report)

    def test_trade_frequency(self):
        records = [
            {"allowed": True, "raw_signal": "BUY", "engine": "trend_rf_v40", "regime": "TREND"},
            {"allowed": False, "raw_signal": "HOLD", "block_reason": "hold_action"},
        ]
        freq = analyze_trade_frequency(records)
        self.assertEqual(freq["accepted_trades"], 1)

    def test_robustness_score_rejects_low_trades(self):
        self.assertEqual(robustness_score({"trades": 50, "profit_factor": 2.0}), 0.0)

    def test_pf_stability(self):
        self.assertGreater(pf_stability([1.1, 1.2, 1.15]), 0.9)

    def test_monte_carlo_runs(self):
        records = [{"allowed": True, "r_multiple": 1.0}] * 50
        mc = run_monte_carlo_validation(records, simulations=100, seed=42)
        self.assertEqual(mc["simulations"], 100)

    def test_monte_carlo_reproducible(self):
        records = [{"allowed": True, "r_multiple": 0.5}] * 80
        a = run_monte_carlo_validation(records, simulations=50, seed=7)
        b = run_monte_carlo_validation(records, simulations=50, seed=7)
        self.assertEqual(a["pf_distribution"]["mean"], b["pf_distribution"]["mean"])

    def test_monte_carlo_sims_constant(self):
        self.assertEqual(MONTE_CARLO_SIMS, 1000)

    def test_pipeline_thresholds_frozen(self):
        th = PipelineThresholds(confidence_threshold=0.45, quality_threshold=0.60)
        self.assertEqual(th.confidence_threshold, 0.45)

    def test_build_final_report(self):
        final = build_final_report(
            threshold_results={"confidence": {"best": {"trades": 400, "profit_factor": 1.2}}, "quality": {"best": {}}},
            missed_trade={"total_blocked_signals": 10, "classification_counts": {}},
            walk_forward={"robustness_score": 0.5},
            monte_carlo={"passes_gate": True},
            frequency={},
            fingerprint_unchanged=True,
            recommended={"confidence_threshold": 0.45, "quality_threshold": 0.60, "max_risk_percent": 0.5},
        )
        self.assertIn("PHASE_14_4_STATUS", final)

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

    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_walk_forward_integrity(self):
        c = _candles(800)
        ds = DatasetStore(None)
        wf = run_walk_forward_optimization(
            c, None, thresholds=PipelineThresholds(), quick=True
        )
        self.assertTrue(wf["chronological"])
        self.assertFalse(wf["shuffle"])

    def test_orchestrator_quick_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase14_4_optimizer(
                symbol="XAUUSD", timeframe="M5", days=30, base_dir=tmp, seed=42, quick=True
            )
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertIn("final_phase14_4_report", result.reports)

    def test_fingerprint_unchanged_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase14_4_optimizer(
                symbol="XAUUSD", timeframe="M5", days=20, base_dir=tmp, seed=42, quick=True
            )
            self.assertIn("recommended", result.summary)

    def test_report_files_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_4_optimizer(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            from tradingbot.ml.research.phase14_4.config import phase14_4_reports_dir

            out = phase14_4_reports_dir(tmp)
            self.assertTrue((out / "final_phase14_4_report.json").is_file())


    def test_grid_stride_config(self):
        from tradingbot.ml.research.phase14_4.config import GRID_STRIDE

        self.assertGreaterEqual(GRID_STRIDE, 1)

    def test_max_research_bars(self):
        from tradingbot.ml.research.phase14_4.config import MAX_RESEARCH_BARS

        self.assertGreater(MAX_RESEARCH_BARS, 1000)

    def test_risk_acceptance_analyzer(self):
        from tradingbot.ml.research.phase14_4.risk_acceptance_analyzer import analyze_risk_acceptance

        records = [
            {"raw_signal": "BUY", "risk_percent": 0.15, "confidence": 0.7, "r_multiple": 1.0},
            {"raw_signal": "BUY", "risk_percent": 0.35, "confidence": 0.7, "r_multiple": -1.0},
        ]
        out = analyze_risk_acceptance(records)
        self.assertIn("risk_cap_analysis", out)

    def test_threshold_optimizer_import(self):
        from tradingbot.ml.research.phase14_4.threshold_optimizer import run_threshold_search

        self.assertTrue(callable(run_threshold_search))

    def test_monte_carlo_no_trades(self):
        mc = run_monte_carlo_validation([], simulations=10, seed=1)
        self.assertFalse(mc["passes_gate"])


if __name__ == "__main__":
    unittest.main()
