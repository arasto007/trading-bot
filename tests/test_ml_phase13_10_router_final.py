"""Phase 13.10 — final router validation tests."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import phase9_9_model_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase13_10.config import (
    EXPECTED_FINGERPRINT,
    MIN_MONTE_CARLO_PROFITABLE,
    MIN_TREND_TRADES_PASS,
    MIN_TRADES_REJECT,
    THRESHOLD_GRID,
    phase13_10_reports_dir,
)
from tradingbot.ml.research.phase13_10.monte_carlo import run_monte_carlo_phase13_10
from tradingbot.ml.research.phase13_10.orchestrator import run_phase13_10_router_final
from tradingbot.ml.research.phase13_10.robust_score import threshold_composite_score
from tradingbot.ml.research.phase13_10.trend_audit.funnel_analyzer import audit_trend_funnel
from tradingbot.ml.research.phase13_10.walk_forward import run_expanding_walk_forward
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_d
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, protected_columns
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.router_optimizer.optimizer_types import OptimizerConfig, RegimeThresholdParams

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase13_10"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")
FORBIDDEN_STRINGS = ("order_send", "trade_request", "mt5_execution")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candles(n: int = 900, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2021-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300.0 + rng.normal(0, 0.5, n).cumsum()
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close},
        index=ts,
    )


def _setup(tmp: str) -> None:
    store = DatasetStore(tmp)
    ts = pd.date_range("2021-01-01", periods=400, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    store.store_v2(
        "XAUUSD",
        "M5",
        pd.DataFrame(
            {
                "timestamp": ts,
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "label": [0, 1] * 200,
                "ema50_slope": rng.normal(0, 1, 400).tolist(),
                "candle_direction": rng.normal(0, 1, 400).tolist(),
                "structure_distance": rng.normal(0, 1, 400).tolist(),
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
            }
        ),
    )
    CandleStore(tmp).store("XAUUSD", "M5", _candles(900))


class TestPhase1310RouterFinal(unittest.TestCase):
    def test_unified_feature_integrity(self):
        c = _candles(700)
        rng = np.random.default_rng(1)
        ds = pd.DataFrame(
            {
                "timestamp": pd.date_range("2021-01-01", periods=200, freq="5min", tz="UTC"),
                "ema50_slope": rng.normal(0, 1, 200),
                "candle_direction": rng.normal(0, 1, 200),
                "structure_distance": rng.normal(0, 1, 200),
            }
        )
        unified = build_unified_frame(c, ds)
        self.assertGreater(float(unified["ema50_slope"].abs().mean()), 0.01)
        self.assertIn("phase99_ema50_slope", unified.columns)
        for col in protected_columns():
            self.assertIn(col, unified.columns)

    def test_no_dataset_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            store = DatasetStore(tmp)
            before = store.load_v2("XAUUSD", "M5")
            fp_before = dataset_content_fingerprint(before)
            run_phase13_10_router_final(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            after = store.load_v2("XAUUSD", "M5")
            fp_after = dataset_content_fingerprint(after)
            self.assertEqual(fp_before, fp_after)

    def test_no_execution_imports(self):
        for py in PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for token in FORBIDDEN:
                            self.assertNotIn(token, alias.name)

    def test_no_forbidden_strings_in_package(self):
        for py in PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for token in FORBIDDEN_STRINGS:
                self.assertNotIn(token, text)

    def test_threshold_grid_constraints(self):
        self.assertEqual(len(THRESHOLD_GRID), 6)
        self.assertIn(0.45, THRESHOLD_GRID)
        self.assertIn(0.30, THRESHOLD_GRID)

    def test_trade_floor_enforcement(self):
        score = threshold_composite_score({"trades": 50, "profit_factor": 3.0}, walk_forward_score=0.9)
        self.assertEqual(score, 0.0)

    def test_walk_forward_integrity(self):
        c = _candles(2000)
        cfg = OptimizerConfig(regime_params=RegimeThresholdParams(), policy="A", seed=42)
        wf = run_expanding_walk_forward(c, None, config=cfg, seed=42, quick=True)
        self.assertTrue(wf["chronological"])
        self.assertFalse(wf["shuffle"])
        self.assertIn("windows", wf)

    def test_monte_carlo_reproducibility(self):
        trades = [{"type": "trade", "R_multiple": 1.0}] * 120
        a = run_monte_carlo_phase13_10(trades, simulations=100, seed=42)
        b = run_monte_carlo_phase13_10(trades, simulations=100, seed=42)
        self.assertEqual(a["profitable_pct"], b["profitable_pct"])
        self.assertEqual(a["pf_distribution"]["mean"], b["pf_distribution"]["mean"])

    def test_monte_carlo_gate_threshold(self):
        self.assertEqual(MIN_MONTE_CARLO_PROFITABLE, 0.95)

    def test_router_funnel_audit_runs(self):
        c = _candles(600)
        report = audit_trend_funnel(c, None, rule_fn=evaluate_variant_d)
        self.assertIn("funnel", report)
        self.assertIn("primary_bottleneck", report)

    def test_phase99_checksum_unchanged(self):
        path = phase9_9_model_path(None)
        if path.is_file():
            h1 = _sha256(path)
            with tempfile.TemporaryDirectory() as tmp:
                _setup(tmp)
                run_phase13_10_router_final(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            h2 = _sha256(path)
            self.assertEqual(h1, h2)

    def test_orchestrator_quick_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase13_10_router_final(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertIn("trend_funnel_report", result.reports)
            final_path = phase13_10_reports_dir(tmp) / "final_phase13_10_report.json"
            self.assertTrue(final_path.is_file())
            payload = json.loads(final_path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("phase"), "13.10")
            self.assertIn("acceptance", payload)

    def test_expected_fingerprint_constant(self):
        self.assertEqual(EXPECTED_FINGERPRINT, "70b38325ee1c7e1e")

    def test_trend_trade_pass_constant(self):
        self.assertGreaterEqual(MIN_TREND_TRADES_PASS, 100)
        self.assertEqual(MIN_TRADES_REJECT, 100)


if __name__ == "__main__":
    unittest.main()
