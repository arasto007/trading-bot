"""Phase 13.7 — router stability tests."""

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

from tradingbot.ml.data.paths import phase13_4_reports_dir, phase9_9_model_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase13_7.config import MIN_TRADES_SOFT, MIN_TRADES_STRONG, phase13_7_final_report_path, phase13_7_reports_dir
from tradingbot.ml.research.phase13_7.initial_audit import build_initial_audit
from tradingbot.ml.research.phase13_7.monte_carlo_validator import run_monte_carlo
from tradingbot.ml.research.phase13_7.orchestrator import _artifact_checksums, run_phase13_7_stability
from tradingbot.ml.research.phase13_7.robust_score import robust_composite_score
from tradingbot.ml.research.phase13_7.trade_constraints import apply_trade_floor, constraint_status, passes_minimum_trades
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase13_7"
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
        {
            "open": close,
            "high": close + rng.uniform(0.2, 1.2, n),
            "low": close - rng.uniform(0.2, 1.2, n),
            "close": close,
        },
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


class TestPhase137RouterStability(unittest.TestCase):
    def test_minimum_trade_constraints(self):
        tiny = {"trades": 2, "profit_factor": 1.98, "expectancy": 0.5, "max_drawdown": 0.01}
        self.assertFalse(passes_minimum_trades(tiny))
        status = constraint_status(tiny)
        self.assertTrue(status["rejected"])
        self.assertTrue(status["strong_reject"])
        score = robust_composite_score(tiny, walk_forward_score=0.8)
        self.assertEqual(score, 0.0)

    def test_optimizer_rejects_tiny_samples(self):
        metrics = {"trades": 50, "profit_factor": 2.0, "expectancy": 1.0, "max_drawdown": 0.05}
        self.assertEqual(apply_trade_floor(0.9, metrics, minimum=MIN_TRADES_SOFT), 0.0)
        ok = {"trades": MIN_TRADES_STRONG, "profit_factor": 1.1, "expectancy": 0.1, "max_drawdown": 0.2}
        self.assertGreater(robust_composite_score(ok, walk_forward_score=0.4), 0.0)

    def test_robust_score_bounded(self):
        score = robust_composite_score(
            {"trades": 600, "profit_factor": 1.5, "expectancy": 0.2, "max_drawdown": 0.15},
            walk_forward_score=0.5,
        )
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.5)

    def test_monte_carlo_runs(self):
        trades = [
            {"type": "trade", "R_multiple": 1.0},
            {"type": "trade", "R_multiple": -0.5},
            {"type": "trade", "R_multiple": 2.0},
        ]
        mc = run_monte_carlo(trades, simulations=50, seed=1)
        self.assertEqual(mc["simulations"], 50)
        self.assertIn("mean_pf", mc)

    def test_initial_audit_from_phase13_6(self):
        audit = build_initial_audit(None)
        self.assertEqual(audit["phase"], "13.7")
        self.assertIn("why_overfit_happened", audit)

    def test_no_forbidden_imports(self):
        for py in PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_execution_strings(self):
        for py in PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for token in FORBIDDEN_STRINGS:
                self.assertNotIn(token, text)

    def test_walk_forward_no_shuffle(self):
        from tradingbot.ml.research.phase13_7.walk_forward_validator import run_walk_forward_for_variant
        from tradingbot.ml.research.phase13_7.config import ROUTER_VARIANTS
        from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame

        c = _candles(500)
        merged = prepare_merged_frame(c, None)
        wf = run_walk_forward_for_variant(merged, c, ROUTER_VARIANTS[0], quick=True)
        self.assertTrue(wf["chronological"])
        self.assertFalse(wf["shuffle"])

    def test_phase9_9_checksum_unchanged(self):
        if not phase9_9_model_path(None).is_file():
            self.skipTest("phase9_9 artifacts missing")
        before = _sha256(phase9_9_model_path(None))
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 artifacts missing")
            run_phase13_7_stability(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
        after = _sha256(phase9_9_model_path(None))
        self.assertEqual(before, after)

    def test_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 artifacts missing")
            fp_before = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            run_phase13_7_stability(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            fp_after = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp_before, fp_after)

    def test_full_pipeline_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 artifacts missing")
            result = run_phase13_7_stability(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            report = json.loads(phase13_7_final_report_path(tmp).read_text(encoding="utf-8"))
            self.assertIn("PHASE_13_7_FINAL_REPORT", report)
            self.assertTrue(report["fingerprint_unchanged"])
            self.assertFalse(report["connected_to_live_trading"])
            out = phase13_7_reports_dir(tmp)
            for name in (
                "initial_audit.json",
                "robust_score_comparison.json",
                "trend_routing_debug.json",
                "range_failure_analysis.json",
                "walk_forward_results.json",
                "monte_carlo_results.json",
            ):
                self.assertTrue((out / name).is_file())


if __name__ == "__main__":
    unittest.main()
