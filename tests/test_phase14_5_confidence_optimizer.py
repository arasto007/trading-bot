"""Phase 14.5 — confidence operating point tests."""

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
from tradingbot.ml.research.phase14_5.adaptive_threshold_optimizer import composite_score, rank_thresholds, select_best_threshold
from tradingbot.ml.research.phase14_5.confidence_sweep import run_confidence_sweep
from tradingbot.ml.research.phase14_5.config import (
    CONFIDENCE_GRID,
    EXPECTED_FINGERPRINT,
    MIN_TRADE_FLOOR,
    MONTE_CARLO_SIMS,
    WF_YEARS,
)
from tradingbot.ml.research.phase14_5.monte_carlo_validator import run_monte_carlo_validation
from tradingbot.ml.research.phase14_5.opportunity_analyzer import analyze_opportunities, classify_opportunity
from tradingbot.ml.research.phase14_5.orchestrator import run_phase14_5_optimizer
from tradingbot.ml.research.phase14_5.pipeline_runner import RegimeConfidencePolicy, sweep_metrics
from tradingbot.ml.research.phase14_5.report_generator import build_final_report
from tradingbot.ml.research.phase14_5.walk_forward_validator import run_walk_forward_validation

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase14_5"
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


class TestPhase145ConfidenceOptimizer(unittest.TestCase):
    def test_confidence_grid_size(self):
        self.assertEqual(len(CONFIDENCE_GRID), 6)

    def test_min_trade_floor(self):
        self.assertEqual(MIN_TRADE_FLOOR, 300)

    def test_wf_years_chronological(self):
        self.assertEqual(WF_YEARS, (2021, 2022, 2023, 2024, 2025, 2026))

    def test_monte_carlo_sims_constant(self):
        self.assertEqual(MONTE_CARLO_SIMS, 1000)

    def test_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_classify_false_rejection(self):
        self.assertEqual(
            classify_opportunity({"allowed": False, "raw_signal": "BUY", "r_multiple": 2.0}),
            "false_rejection",
        )

    def test_classify_correct_rejection(self):
        self.assertEqual(
            classify_opportunity({"allowed": False, "raw_signal": "SELL", "r_multiple": -1.0}),
            "correct_rejection",
        )

    def test_classify_low_confidence_winner(self):
        self.assertEqual(
            classify_opportunity({"allowed": True, "raw_signal": "BUY", "confidence": 0.4, "r_multiple": 0.3}),
            "low_confidence_winner",
        )

    def test_classify_high_confidence_loser(self):
        self.assertEqual(
            classify_opportunity({"allowed": True, "raw_signal": "BUY", "confidence": 0.7, "r_multiple": -0.5}),
            "high_confidence_loser",
        )

    def test_opportunity_analyzer(self):
        records = [
            {"allowed": False, "raw_signal": "BUY", "r_multiple": 2.0, "confidence": 0.4},
            {"allowed": True, "raw_signal": "BUY", "r_multiple": 1.0, "confidence": 0.8},
        ]
        report = analyze_opportunities(records)
        self.assertIn("classification_counts", report)

    def test_sweep_metrics_precision_recall(self):
        records = [
            {"raw_signal": "BUY", "allowed": True, "r_multiple": 1.0},
            {"raw_signal": "BUY", "allowed": False, "r_multiple": 1.0},
            {"raw_signal": "SELL", "allowed": True, "r_multiple": -1.0},
        ]
        m = sweep_metrics(records)
        self.assertIn("precision", m)
        self.assertIn("recall", m)

    def test_composite_score_penalizes_low_trades(self):
        self.assertEqual(composite_score({"effective_trades_est": 50, "expectancy": 2.0}), 0.0)

    def test_composite_score_positive(self):
        score = composite_score(
            {
                "effective_trades_est": 400,
                "expectancy": 0.5,
                "max_drawdown": 0.1,
                "precision": 0.6,
            },
            robustness=0.7,
        )
        self.assertGreater(score, 0.0)

    def test_select_best_threshold(self):
        rows = [
            {"confidence_threshold": 0.35, "rejected": False, "effective_trades_est": 400, "expectancy": 0.4, "profit_factor": 1.2, "max_drawdown": 0.1, "precision": 0.5},
            {"confidence_threshold": 0.55, "rejected": True, "effective_trades_est": 50},
        ]
        best = select_best_threshold(rows, wf_scores={0.35: 0.6})
        self.assertEqual(best["confidence_threshold"], 0.35)

    def test_rank_thresholds(self):
        rows = [
            {"confidence_threshold": 0.35, "rejected": False, "effective_trades_est": 400, "expectancy": 0.4, "profit_factor": 1.2, "max_drawdown": 0.1, "precision": 0.5},
            {"confidence_threshold": 0.40, "rejected": False, "effective_trades_est": 350, "expectancy": 0.6, "profit_factor": 1.4, "max_drawdown": 0.1, "precision": 0.55},
        ]
        ranked = rank_thresholds(rows, wf_scores={0.35: 0.5, 0.40: 0.7})
        self.assertEqual(ranked[0]["rank"], 1)

    def test_regime_policy_high_vol_blocks(self):
        policy = RegimeConfidencePolicy()
        self.assertFalse(policy.passes(0.9, "HIGH_VOLATILITY"))

    def test_regime_policy_range_pass(self):
        policy = RegimeConfidencePolicy(thresholds={"RANGE": 0.35, "TREND": 0.40, "HIGH_VOLATILITY": 1.0})
        self.assertTrue(policy.passes(0.40, "RANGE"))

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
        wf = run_walk_forward_validation(c, None, confidence_threshold=0.45, quick=True)
        self.assertTrue(wf["chronological"])
        self.assertFalse(wf["shuffle"])

    def test_build_final_report(self):
        final = build_final_report(
            sweep={"results": []},
            opportunity={"false_rejections": 10},
            regime={"regime_policy": {"RANGE": 0.45}, "combined_metrics": {"accepted_trades": 400}},
            walk_forward={"robustness_score": 0.5},
            monte_carlo={"profitable_pct": 0.96},
            best_fixed={
                "confidence_threshold": 0.40,
                "effective_trades_est": 400,
                "profit_factor": 1.2,
                "expectancy": 0.3,
                "false_acceptance": 5,
            },
            baseline_trades=3,
            baseline_pf=4.0,
            fingerprint_unchanged=True,
            records_best=[],
        )
        self.assertIn("PHASE_14_5_STATUS", final)
        self.assertIn("answers", final)

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

    def test_no_riskgate_modification_strings(self):
        for py in PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8").lower()
            self.assertNotIn("riskgate.", text)

    def test_confidence_sweep_quick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = CandleStore(tmp).load("XAUUSD", "M5")
            dataset = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            sweep = run_confidence_sweep(candles, dataset, quick=True)
            self.assertIn("results", sweep)

    def test_orchestrator_quick_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase14_5_optimizer(
                symbol="XAUUSD", timeframe="M5", days=30, base_dir=tmp, seed=42, quick=True
            )
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertIn("final_phase14_5_report", result.reports)

    def test_report_files_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase14_5_optimizer(symbol="XAUUSD", timeframe="M5", days=15, base_dir=tmp, quick=True)
            from tradingbot.ml.research.phase14_5.config import phase14_5_reports_dir

            out = phase14_5_reports_dir(tmp)
            self.assertTrue((out / "final_phase14_5_report.json").is_file())
            self.assertTrue((out / "confidence_sweep.json").is_file())
            self.assertTrue((out / "opportunity_analysis.json").is_file())


if __name__ == "__main__":
    unittest.main()
