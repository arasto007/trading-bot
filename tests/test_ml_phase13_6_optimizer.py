"""Phase 13.6 — router optimizer tests."""

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

from tradingbot.ml.data.paths import (
    phase13_4_reports_dir,
    phase13_6_final_report_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.router_optimizer.failure_analyzer import analyze_failures, FAILURE_CATEGORIES
from tradingbot.ml.research.router_optimizer.optimizer_types import (
    RegimeThresholdParams,
    OptimizerConfig,
    classify_regime_row,
    composite_score,
    baseline_phase135_config,
)
from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame, run_optimized_backtest
from tradingbot.ml.research.router_optimizer.robustness_validator import robustness_score
from tradingbot.ml.research.router_optimizer.threshold_optimizer import ML_THRESHOLDS, optimize_thresholds
from tradingbot.ml.research.router_optimizer.trade_filter_optimizer import REGIME_POLICIES, resolve_routing_action
from tradingbot.ml.research.router_optimizer.orchestrator import _artifact_checksums, run_phase13_6_optimizer

OPT_PKG = ROOT / "tradingbot" / "ml" / "research" / "router_optimizer"
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
    store.store_v2(
        "XAUUSD",
        "M5",
        pd.DataFrame(
            {
                "timestamp": ts,
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "label": [0, 1] * 200,
                "ema50_slope": rng_like(400),
                "candle_direction": rng_like(400),
                "structure_distance": rng_like(400),
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
            }
        ),
    )
    CandleStore(tmp).store("XAUUSD", "M5", _candles(900))


def rng_like(n: int) -> list[float]:
    rng = np.random.default_rng(7)
    return rng.normal(0, 1, n).tolist()


class TestPhase136Optimizer(unittest.TestCase):
    def test_regime_classify_tunable(self):
        row = pd.Series({"adx": 28, "ema50_slope": 0.2, "atr_percentile": 25, "spread_pips": 0, "volatility": 1})
        self.assertEqual(classify_regime_row(row, RegimeThresholdParams(adx_trend_min=25)), "TREND")
        self.assertEqual(classify_regime_row(row, RegimeThresholdParams(adx_trend_min=30)), "RANGE")

    def test_routing_policies(self):
        self.assertEqual(resolve_routing_action("HIGH_VOLATILITY", "A"), "BLOCK")
        self.assertEqual(resolve_routing_action("HIGH_VOLATILITY", "B"), "TREND")
        self.assertEqual(resolve_routing_action("TREND", "C"), "BLOCK")

    def test_composite_score_bounded(self):
        score = composite_score({"profit_factor": 2.0, "expectancy": 0.5, "max_drawdown": 0.1}, robustness=0.6)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.5)

    def test_threshold_grid(self):
        self.assertEqual(len(ML_THRESHOLDS), 5)

    def test_policy_count(self):
        self.assertEqual(len(REGIME_POLICIES), 4)

    def test_failure_categories(self):
        self.assertEqual(len(FAILURE_CATEGORIES), 6)

    def test_robustness_score(self):
        score = robustness_score([{"profit_factor": 1.2}, {"profit_factor": 1.1}])
        self.assertGreaterEqual(score, 0.0)

    def test_no_forbidden_imports(self):
        for py in OPT_PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_execution_strings(self):
        for py in OPT_PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for token in FORBIDDEN_STRINGS:
                self.assertNotIn(token, text)

    def test_chronological_backtest(self):
        if not phase9_9_model_path(None).is_file():
            self.skipTest("phase9_9 artifacts missing")
        from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache

        c = _candles(700)
        merged = prepare_merged_frame(c, None)
        cache = EngineCache(c, seed=42)
        bt = run_optimized_backtest(
            merged, c, config=OptimizerConfig(regime_params=RegimeThresholdParams()), engine_cache=cache
        )
        self.assertTrue(bt["chronological"])
        self.assertFalse(bt["shuffle"])

    def test_threshold_reproducible(self):
        if not phase9_9_model_path(None).is_file():
            self.skipTest("phase9_9 artifacts missing")
        c = _candles(650, seed=3)
        merged = prepare_merged_frame(c, None)
        from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache

        cache = EngineCache(c, seed=99)
        r1 = optimize_thresholds(merged, c, seed=99, engine_cache=cache, quick=True)
        r2 = optimize_thresholds(merged, c, seed=99, engine_cache=cache, quick=True)
        self.assertEqual(r1["best_threshold"], r2["best_threshold"])

    def test_phase9_9_checksum_unchanged(self):
        if not phase9_9_model_path(None).is_file():
            self.skipTest("phase9_9 artifacts missing")
        from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache

        before = _sha256(phase9_9_model_path(None))
        c = _candles(500)
        merged = prepare_merged_frame(c, None)
        cache = EngineCache(c, seed=42)
        run_optimized_backtest(
            merged, c, config=OptimizerConfig(regime_params=RegimeThresholdParams()), engine_cache=cache
        )
        after = _sha256(phase9_9_model_path(None))
        self.assertEqual(before, after)

    def test_phase13_4_checksum_unchanged(self):
        path = phase13_4_reports_dir(None) / "trend_ml_best_model.json"
        if not path.is_file():
            self.skipTest("phase13_4 report missing")
        from tradingbot.ml.research.router_optimizer.engine_cache import EngineCache

        before = _sha256(path)
        c = _candles(500)
        merged = prepare_merged_frame(c, None)
        cache = EngineCache(c, seed=42)
        run_optimized_backtest(
            merged, c, config=OptimizerConfig(regime_params=RegimeThresholdParams()), engine_cache=cache
        )
        after = _sha256(path)
        self.assertEqual(before, after)

    def test_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 artifacts missing")
            fp_before = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            cs_before = _artifact_checksums(tmp)
            run_phase13_6_optimizer(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            fp_after = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            cs_after = _artifact_checksums(tmp)
            self.assertEqual(fp_before, fp_after)
            self.assertEqual(cs_before, cs_after)

    def test_full_pipeline_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 artifacts missing")
            result = run_phase13_6_optimizer(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            report = json.loads(phase13_6_final_report_path(tmp).read_text(encoding="utf-8"))
            self.assertIn("PHASE_13_6_FINAL_REPORT", report)
            self.assertTrue(report["fingerprint_unchanged"])
            self.assertFalse(report["connected_to_live_trading"])


if __name__ == "__main__":
    unittest.main()
