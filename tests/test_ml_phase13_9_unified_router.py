"""Phase 13.9 — unified router tests."""

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
from tradingbot.ml.research.phase13_9.config import MIN_SIGNALS_TARGET, phase13_9_final_report_path, phase13_9_reports_dir
from tradingbot.ml.research.phase13_9.feature_parity_checker import check_feature_parity
from tradingbot.ml.research.phase13_9.orchestrator import run_phase13_9_unified_router
from tradingbot.ml.research.phase13_9.signal_loss_analyzer import analyze_signal_loss
from tradingbot.ml.research.phase13_9.trend_adapter_validator import validate_trend_adapter
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase13_9"
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


class TestPhase139UnifiedRouter(unittest.TestCase):
    def test_unified_preserves_ema50_slope(self):
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
        canon = build_ml_features(c)
        unified = build_unified_frame(c, ds)
        # trend ema50_slope must not be zeroed by dataset
        self.assertGreater(float(unified["ema50_slope"].abs().mean()), 0.01)
        self.assertIn("phase99_ema50_slope", unified.columns)

    def test_signal_count_recovery(self):
        c = _candles(800)
        ds = DatasetStore(None)
        # synthetic dataset with wrong slopes
        ts = pd.date_range("2021-01-01", periods=800, freq="5min", tz="UTC")
        bad = pd.DataFrame({"timestamp": ts, "ema50_slope": [0.0] * 800, "candle_direction": [0.0] * 800, "structure_distance": [0.0] * 800})
        loss = analyze_signal_loss(c, bad)
        self.assertGreaterEqual(loss["unified_signals"], loss["legacy_signals"])

    def test_feature_parity_runs(self):
        c = _candles(600)
        report = check_feature_parity(c, None)
        self.assertIn("answers", report)

    def test_trend_validation(self):
        c = _candles(650)
        v = validate_trend_adapter(c, None)
        self.assertIn("canonical", v)

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

    def test_walk_forward_chronological(self):
        from tradingbot.ml.research.phase13_9.walk_forward_validator import run_walk_forward_unified
        from tradingbot.ml.research.router_optimizer.optimizer_types import baseline_phase135_config, OptimizerConfig

        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            c = CandleStore(tmp).load("XAUUSD", "M5")
            raw = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            cfg = OptimizerConfig(**{**baseline_phase135_config().__dict__, "seed": 42})
            wf = run_walk_forward_unified(c, raw, config=cfg, quick=True, base_dir=tmp)
            self.assertTrue(wf["chronological"])
            self.assertFalse(wf["shuffle"])

    def test_phase9_9_checksum(self):
        if not phase9_9_model_path(None).is_file():
            self.skipTest("phase9_9 missing")
        before = _sha256(phase9_9_model_path(None))
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase13_9_unified_router(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
        self.assertEqual(before, _sha256(phase9_9_model_path(None)))

    def test_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 missing")
            fp0 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            run_phase13_9_unified_router(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            fp1 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp0, fp1)

    def test_full_pipeline_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 missing")
            result = run_phase13_9_unified_router(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            out = phase13_9_reports_dir(tmp)
            for name in (
                "feature_parity_report.json",
                "signal_loss_report.json",
                "router_comparison.json",
                "phase13_9_final_report.json",
            ):
                self.assertTrue((out / name).is_file(), name)
            report = json.loads(phase13_9_final_report_path(tmp).read_text(encoding="utf-8"))
            self.assertIn("signal_preservation", report)


if __name__ == "__main__":
    unittest.main()
