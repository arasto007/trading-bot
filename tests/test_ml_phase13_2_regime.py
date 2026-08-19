"""Phase 13.2 — market regime detection research tests."""

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

from tradingbot.ml.data.paths import phase13_2_regime_report_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.regime_detector.orchestrator import run_phase13_2_regime
from tradingbot.ml.research.regime_detector.regime_classifier import REGIME_LABELS, rule_classify
from tradingbot.ml.research.regime_detector.regime_features import (
    REGIME_FEATURE_COLUMNS,
    compute_regime_features_from_candles,
    enrich_from_dataset,
)
from tradingbot.ml.research.regime_detector.regime_validator import (
    build_expanding_windows,
    validate_rule_baseline,
    walk_forward_validate,
)
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

REGIME_PKG = ROOT / "tradingbot" / "ml" / "research" / "regime_detector"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
    "order_send",
)
TEST_MIN_SAMPLES = 80


def _synthetic_source(n: int = 1500, *, seed: int = 42, start_year: int = 2021) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{start_year}-01-01", periods=n, freq="5min", tz="UTC")
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": rng.choice(["order_block", "choch", "fvg"], size=n),
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "entry_price": 2300.0 + rng.normal(0, 1, n),
        "direction": rng.choice([1, -1], size=n),
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": rng.choice([0, 1], size=n),
        "risk_unit": rng.uniform(1, 5, n),
        "split": "train",
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "volatility_regime": rng.choice([0.0, 0.5, 1.0], size=n),
        "trend_strength": rng.uniform(5, 80, n),
        "atr_percentile": rng.uniform(5, 98, n),
        "ema50_slope": rng.normal(0, 0.4, n),
        "ema_cross_state": rng.choice([-1.0, 0.0, 1.0], size=n),
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    return pd.DataFrame(rows)


def _write_candles(tmp: str, n: int = 800) -> None:
    ts = pd.date_range("2021-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    close = 2300.0 + rng.normal(0, 0.3, n).cumsum()
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + rng.uniform(0.1, 0.8, n),
            "low": close - rng.uniform(0.1, 0.8, n),
            "close": close,
        },
        index=ts,
    )
    CandleStore(tmp).store("XAUUSD", "M5", df)


def _setup(tmp: str) -> str:
    store = DatasetStore(tmp)
    store.store_v2("XAUUSD", "M5", _synthetic_source())
    _write_candles(tmp)
    df = store.load_v2("XAUUSD", "M5")
    assert df is not None
    return dataset_content_fingerprint(df)


class TestPhase132Regime(unittest.TestCase):
    def test_regime_feature_columns(self):
        self.assertIn("adx", REGIME_FEATURE_COLUMNS)
        self.assertIn("ema50_slope", REGIME_FEATURE_COLUMNS)

    def test_rule_classifier_labels(self):
        row = pd.Series({"adx": 30, "atr_percentile": 40, "ema50_slope": 0.3, "spread_pips": 1})
        label = rule_classify(row)
        self.assertIn(label, REGIME_LABELS)

    def test_no_forbidden_imports(self):
        for py in REGIME_PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for prefix in FORBIDDEN:
                        if node.module.startswith(prefix.replace(".adapters", "")):
                            self.fail(f"{py.name} imports {node.module}")

    def test_no_execution_imports(self):
        for py in REGIME_PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            self.assertNotIn("mt5_execution", text)
            self.assertNotIn("order_send", text)

    def test_chronological_windows_no_shuffle(self):
        ts = pd.date_range("2021-01-01", periods=500, freq="5min", tz="UTC")
        df = pd.DataFrame({"timestamp": ts})
        windows = build_expanding_windows(df)
        self.assertTrue(len(windows) >= 1)

    def test_candle_features_reproducible(self):
        ts = pd.date_range("2021-01-01", periods=500, freq="5min", tz="UTC")
        rng = np.random.default_rng(1)
        close = 2300.0 + rng.normal(0, 0.2, 500).cumsum()
        candles = pd.DataFrame(
            {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close},
            index=ts,
        )
        f1 = compute_regime_features_from_candles(candles)
        f2 = compute_regime_features_from_candles(candles)
        pd.testing.assert_frame_equal(f1, f2)

    def test_dataset_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp_before = _setup(tmp)
            run_phase13_2_regime(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp)
            fp_after = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp_before, fp_after)

    def test_walk_forward_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            raw = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            feats = enrich_from_dataset(raw)
            wf = walk_forward_validate(feats, model_name="logistic", seed=42)
            self.assertTrue(wf["chronological"])
            self.assertFalse(wf["shuffle"])

    def test_full_pipeline_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = run_phase13_2_regime(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertTrue(Path(result.reports["regime_report"]).is_file())
            report = json.loads(phase13_2_regime_report_path(tmp).read_text(encoding="utf-8"))
            self.assertTrue(report["fingerprint_unchanged"])
            self.assertFalse(report["connected_to_live_trading"])


if __name__ == "__main__":
    unittest.main()
