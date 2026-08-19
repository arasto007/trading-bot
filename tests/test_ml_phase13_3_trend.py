"""Phase 13.3 — trend strategy research tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import phase13_3_trend_report_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.trend_strategy.report import run_phase13_3_trend
from tradingbot.ml.research.trend_strategy.trend_backtest import run_trend_backtest
from tradingbot.ml.research.trend_strategy.trend_features import TREND_FEATURE_COLUMNS, compute_trend_features
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules
from tradingbot.ml.research.trend_strategy.trend_signal import build_trend_signal

TREND_PKG = ROOT / "tradingbot" / "ml" / "research" / "trend_strategy"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")


def _candles(n: int = 600, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2021-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300.0 + rng.normal(0, 0.4, n).cumsum()
    return pd.DataFrame(
        {
            "open": close,
            "high": close + rng.uniform(0.2, 1.0, n),
            "low": close - rng.uniform(0.2, 1.0, n),
            "close": close,
        },
        index=ts,
    )


def _setup(tmp: str) -> None:
    store = DatasetStore(tmp)
    ts = pd.date_range("2021-01-01", periods=200, freq="5min", tz="UTC")
    store.store_v2(
        "XAUUSD",
        "M5",
        pd.DataFrame(
            {
                "timestamp": ts,
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "label": [0, 1] * 100,
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
            }
        ),
    )
    CandleStore(tmp).store("XAUUSD", "M5", _candles(600))


class TestPhase133Trend(unittest.TestCase):
    def test_trend_feature_columns(self):
        self.assertIn("ema50_slope", TREND_FEATURE_COLUMNS)
        self.assertIn("breakout_distance", TREND_FEATURE_COLUMNS)

    def test_only_trend_regime_signals(self):
        row = pd.Series(
            {
                "ema20": 2310,
                "ema50": 2300,
                "ema50_slope": 0.3,
                "adx": 30,
                "higher_high_count": 3,
                "lower_low_count": 1,
            }
        )
        self.assertEqual(evaluate_trend_rules(row, regime="TREND"), "BUY")
        self.assertEqual(evaluate_trend_rules(row, regime="RANGE"), "HOLD")

    def test_signal_has_sl_tp(self):
        row = pd.Series(
            {
                "timestamp": "2021-06-01T10:00:00+00:00",
                "close": 2300.0,
                "high": 2301.0,
                "low": 2299.0,
                "atr": 5.0,
                "adx": 30,
            }
        )
        sig = build_trend_signal(row, symbol="XAUUSD", direction="BUY")
        self.assertLess(sig["stop_loss"], sig["entry"])
        self.assertGreater(sig["take_profit"], sig["entry"])
        self.assertEqual(sig["rr_ratio"], 2.0)

    def test_no_forbidden_imports(self):
        for py in TREND_PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_execution_strings(self):
        for py in TREND_PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            self.assertNotIn("order_send", text)
            self.assertNotIn("mt5_execution", text)

    def test_features_reproducible(self):
        c = _candles(500, seed=1)
        f1 = compute_trend_features(c)
        f2 = compute_trend_features(c)
        pd.testing.assert_frame_equal(f1, f2)

    def test_backtest_chronological_trend_only(self):
        frame = compute_trend_features(_candles(500))
        bt = run_trend_backtest(frame)
        self.assertTrue(bt["chronological"])
        self.assertFalse(bt["shuffle"])
        self.assertTrue(bt["trend_only"])

    def test_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            fp_before = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            run_phase13_3_trend(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp)
            fp_after = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp_before, fp_after)

    def test_full_pipeline_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase13_3_trend(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertTrue(Path(result.reports["trend_strategy_report"]).is_file())
            report = json.loads(phase13_3_trend_report_path(tmp).read_text(encoding="utf-8"))
            self.assertTrue(report["fingerprint_unchanged"])
            self.assertFalse(report["connected_to_live_trading"])


if __name__ == "__main__":
    unittest.main()
