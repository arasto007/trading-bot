"""Phase 13.4 — trend ML enhancement tests."""

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

from tradingbot.ml.data.paths import phase13_4_trend_ml_report_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS, build_ml_features
from tradingbot.ml.research.trend_ml.label_builder import build_supervised_labels
from tradingbot.ml.research.trend_ml.models import available_trend_ml_candidates, create_trend_ml_model
from tradingbot.ml.research.trend_ml.report import run_phase13_4_trend_ml
from tradingbot.ml.research.trend_ml.trend_ml_filter import DEFAULT_THRESHOLD, apply_trend_ml_filter
from tradingbot.ml.research.trend_ml.validator import walk_forward_validate

TREND_ML_PKG = ROOT / "tradingbot" / "ml" / "research" / "trend_ml"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")


def _candles(n: int = 800, seed: int = 42) -> pd.DataFrame:
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
    ts = pd.date_range("2021-01-01", periods=300, freq="5min", tz="UTC")
    store.store_v2(
        "XAUUSD",
        "M5",
        pd.DataFrame(
            {
                "timestamp": ts,
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "label": [0, 1] * 150,
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
            }
        ),
    )
    CandleStore(tmp).store("XAUUSD", "M5", _candles(800))


class TestPhase134TrendML(unittest.TestCase):
    def test_ml_feature_columns(self):
        self.assertIn("candle_momentum", TREND_ML_FEATURE_COLUMNS)
        self.assertIn("ema50_slope", TREND_ML_FEATURE_COLUMNS)

    def test_model_candidates(self):
        names = available_trend_ml_candidates()
        self.assertIn("logistic", names)
        self.assertIn("random_forest", names)

    def test_labels_chronological(self):
        frame = build_ml_features(_candles(600))
        samples = build_supervised_labels(frame)
        if len(samples) > 1:
            ts = pd.to_datetime(samples["timestamp"], utc=True)
            self.assertTrue(ts.is_monotonic_increasing)
        self.assertIn("successful_trade", samples.columns)

    def test_no_forbidden_imports(self):
        for py in TREND_ML_PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_execution_strings(self):
        for py in TREND_ML_PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            self.assertNotIn("order_send", text)
            self.assertNotIn("mt5_execution", text)

    def test_walk_forward_integrity(self):
        frame = build_ml_features(_candles(800))
        samples = build_supervised_labels(frame)
        if len(samples) < 50:
            self.skipTest("insufficient labeled samples")
        wf = walk_forward_validate(samples, model_name="logistic", seed=42)
        self.assertTrue(wf["chronological"])
        self.assertFalse(wf["shuffle"])
        self.assertEqual(wf["scaler_fit"], "train_only")

    def test_filter_output_shape(self):
        frame = build_ml_features(_candles(500))
        samples = build_supervised_labels(frame)
        if samples.empty:
            self.skipTest("no samples")
        row = samples.iloc[0]
        from sklearn.preprocessing import StandardScaler

        cols = [c for c in TREND_ML_FEATURE_COLUMNS if c in samples.columns]
        scaler = StandardScaler()
        X = samples[cols].astype(float).values
        scaler.fit(X)
        model = create_trend_ml_model("logistic", seed=42)
        model.fit(scaler.transform(X), samples["successful_trade"].values)
        out = apply_trend_ml_filter(row, model=model, scaler=scaler, model_name="logistic")
        self.assertIn("probability", out)
        self.assertIn("allow_trade", out)
        self.assertEqual(out["model_version"], "phase13_4_trend_ml_logistic")
        self.assertEqual(DEFAULT_THRESHOLD, 0.55)

    def test_reproducible_labels(self):
        c = _candles(600, seed=7)
        s1 = build_supervised_labels(build_ml_features(c))
        s2 = build_supervised_labels(build_ml_features(c))
        pd.testing.assert_frame_equal(s1, s2)

    def test_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            fp_before = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            run_phase13_4_trend_ml(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp)
            fp_after = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp_before, fp_after)

    def test_full_pipeline_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase13_4_trend_ml(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertTrue(Path(result.reports["trend_ml_report"]).is_file())
            report = json.loads(phase13_4_trend_ml_report_path(tmp).read_text(encoding="utf-8"))
            self.assertTrue(report["fingerprint_unchanged"])
            self.assertFalse(report["connected_to_live_trading"])
            self.assertTrue(report["ready_for_phase13_5"])


if __name__ == "__main__":
    unittest.main()
