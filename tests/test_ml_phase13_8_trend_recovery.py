"""Phase 13.8 — trend recovery tests."""

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
from tradingbot.ml.research.phase13_8.config import MIN_TRADES_SOFT, phase13_8_final_report_path, phase13_8_reports_dir
from tradingbot.ml.research.phase13_8.orchestrator import _artifact_checksums, run_phase13_8_trend_recovery
from tradingbot.ml.research.phase13_8.threshold_optimizer import optimize_threshold
from tradingbot.ml.research.phase13_8.trend_variants import VARIANTS, evaluate_variant_b
from tradingbot.ml.research.phase13_8.walk_forward import run_walk_forward
from tradingbot.ml.research.phase13_8.trend_feature_research import build_canonical_trend_frame
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

PKG = ROOT / "tradingbot" / "ml" / "research" / "phase13_8"
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


class TestPhase138TrendRecovery(unittest.TestCase):
    def test_minimum_trade_reject(self):
        from tradingbot.ml.research.phase13_8.threshold_optimizer import _robust_score

        score = _robust_score({"trades": 2, "profit_factor": 2.0, "expectancy": 0.5, "max_drawdown": 0.01})
        self.assertEqual(score, 0.0)

    def test_variants_exist(self):
        self.assertEqual(len(VARIANTS), 5)

    def test_walk_forward_chronological(self):
        c = _candles(600)
        frame = build_canonical_trend_frame(c)
        wf = run_walk_forward(frame, symbol="XAUUSD", rule_fn=evaluate_variant_b, quick=True)
        self.assertTrue(wf["chronological"])
        self.assertFalse(wf["shuffle"])

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

    def test_phase9_9_checksum_unchanged(self):
        if not phase9_9_model_path(None).is_file():
            self.skipTest("phase9_9 artifacts missing")
        before = _sha256(phase9_9_model_path(None))
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            run_phase13_8_trend_recovery(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
        after = _sha256(phase9_9_model_path(None))
        self.assertEqual(before, after)

    def test_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 artifacts missing")
            fp_before = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            run_phase13_8_trend_recovery(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            fp_after = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp_before, fp_after)

    def test_full_pipeline_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not phase9_9_model_path(None).is_file():
                self.skipTest("phase9_9 artifacts missing")
            result = run_phase13_8_trend_recovery(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp, quick=True)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            report = json.loads(phase13_8_final_report_path(tmp).read_text(encoding="utf-8"))
            self.assertIn("PHASE_13_8_FINAL_REPORT", report)
            self.assertTrue(report["fingerprint_unchanged"])
            out = phase13_8_reports_dir(tmp)
            for name in (
                "trend_failure_audit.json",
                "trend_variant_results.json",
                "label_comparison.json",
                "trend_ml_comparison.json",
                "threshold_results.json",
                "monte_carlo_results.json",
                "router_comparison.json",
            ):
                self.assertTrue((out / name).is_file())


if __name__ == "__main__":
    unittest.main()
