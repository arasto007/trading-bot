"""Phase 5.0 ML decision layer tests — shadow mode only."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision.confidence import ConfidenceConfig, confidence_from_probability
from tradingbot.ml.decision.logger import DecisionLogger
from tradingbot.ml.decision.logger import DecisionLogger, shadow_log_path
from tradingbot.ml.decision.policy import DecisionPolicy
from tradingbot.ml.decision.predictor import MLPredictor
from tradingbot.ml.decision.schema import MLDecision, direction_label
from tradingbot.ml.decision.shadow import ShadowEngine
from tradingbot.ml.features.registry import feature_names
from tradingbot.ml.models.training import train_baseline_model
from tradingbot.ml.validation._utils import write_json_report

DECISION_PKG = ROOT / "tradingbot" / "ml" / "decision"
FORBIDDEN_IMPORT_PREFIXES = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _make_dataset(n: int = 120, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-06-01", periods=n, freq="5min", tz="UTC")
    n_train = int(n * 0.70)
    n_val = int(n * 0.15)
    splits = ["train"] * n_train + ["validation"] * n_val + ["test"] * (n - n_train - n_val)
    labels = rng.choice([0, 1], size=n, p=[0.45, 0.55])

    row: dict = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": "bos",
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "timeframe_role": "entry_execution",
        "entry_price": 2300.0,
        "direction": rng.choice([1, -1], n),
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": labels,
        "future_window_bars": 72,
        "tp_hit": labels == 1,
        "sl_hit": labels == 0,
        "mfe": rng.uniform(0, 2, n),
        "mae": rng.uniform(0, 1, n),
        "future_return": rng.normal(0, 0.01, n),
        "risk_unit": 10.0,
        "split": splits,
        "dataset_schema_version": "1.0",
    }
    for feat in feature_names():
        row[feat] = rng.normal(0, 1, n)
    row["h4_trend_bias"] = np.where(labels == 1, 1.0, -1.0)
    row["bos_state"] = rng.choice([0.0, 1.0], n)
    row["spread_spike"] = 0.0
    row["spread_zscore"] = 0.1
    return pd.DataFrame(row)


def _setup(tmp: str) -> pd.DataFrame:
    store = DatasetStore(tmp)
    df = _make_dataset()
    store.store("XAUUSD", "M5", df)
    store.save_build_manifest("XAUUSD", "M5", {"dataset_hash": "d5hash", "feature_version": "2.0"})
    train_baseline_model("XAUUSD", "M5", "logistic", base_dir=tmp, params={"max_iter": 200})
    write_json_report(
        reports_dir(tmp) / "optimal_threshold.json",
        {"model": "logistic", "best_threshold": 0.55, "expected_R": 0.2, "winrate": 0.6, "signals": 40},
    )
    return df


class TestSchema(unittest.TestCase):
    def test_decision_schema_works(self):
        d = MLDecision(
            timestamp="2024-01-01T00:00:00+00:00",
            symbol="XAUUSD",
            timeframe="M5",
            model_name="logistic",
            model_version="1.0",
            prediction=1,
            probability=0.71,
            direction="BUY",
            confidence="HIGH",
            threshold_used=0.68,
            accepted=True,
            reason="probability above optimized threshold",
        )
        payload = d.to_dict()
        restored = MLDecision.from_dict(payload)
        self.assertEqual(restored.symbol, "XAUUSD")
        self.assertTrue(restored.accepted)
        self.assertEqual(direction_label(1), "BUY")


class TestConfidence(unittest.TestCase):
    def test_probability_converted_correctly(self):
        self.assertEqual(confidence_from_probability(0.55), "LOW")
        self.assertEqual(confidence_from_probability(0.65), "MEDIUM")
        self.assertEqual(confidence_from_probability(0.75), "HIGH")
        cfg = ConfidenceConfig(high_min=0.80)
        self.assertEqual(confidence_from_probability(0.75, cfg), "MEDIUM")


class TestPredictor(unittest.TestCase):
    def test_model_loads_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            predictor = MLPredictor("XAUUSD", "M5", "logistic", base_dir=tmp).load()
            self.assertEqual(predictor.model_name, "logistic")
            self.assertGreater(len(predictor.feature_columns), 0)
            self.assertEqual(predictor.threshold, 0.55)

    def test_deterministic_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _setup(tmp)
            row = df.iloc[0].to_dict()
            predictor = MLPredictor("XAUUSD", "M5", "logistic", base_dir=tmp).load()
            d1 = predictor.predict_row(row)
            d2 = predictor.predict_row(row)
            self.assertEqual(d1.prediction, d2.prediction)
            self.assertEqual(d1.probability, d2.probability)
            self.assertEqual(d1.features_hash, d2.features_hash)


class TestPolicy(unittest.TestCase):
    def test_threshold_policy_works(self):
        policy = DecisionPolicy()
        decision = MLDecision(
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol="XAUUSD",
            timeframe="M5",
            model_name="logistic",
            model_version="1.0",
            prediction=1,
            probability=0.72,
            direction="BUY",
            confidence="HIGH",
            threshold_used=0.68,
            accepted=False,
            reason="",
        )
        result = policy.evaluate(decision, feature_row={}, required_features=[])
        self.assertTrue(result.accepted)

        decision.probability = 0.60
        result = policy.evaluate(decision, feature_row={}, required_features=[])
        self.assertFalse(result.accepted)

    def test_missing_feature_rejection(self):
        policy = DecisionPolicy()
        decision = MLDecision(
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol="XAUUSD",
            timeframe="M5",
            model_name="logistic",
            model_version="1.0",
            prediction=1,
            probability=0.80,
            direction="BUY",
            confidence="HIGH",
            threshold_used=0.5,
            accepted=False,
            reason="",
        )
        result = policy.evaluate(
            decision,
            feature_row={"ema50_slope": 1.0},
            required_features=["ema50_slope", "rsi_14"],
        )
        self.assertFalse(result.accepted)
        self.assertIn("missing features", result.reason)


class TestShadow(unittest.TestCase):
    def test_shadow_logging_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _setup(tmp)
            row = df.iloc[-1].to_dict()
            predictor = MLPredictor("XAUUSD", "M5", "logistic", base_dir=tmp).load()
            engine = ShadowEngine(predictor, base_dir=tmp)
            record = engine.run(row, system_signal="BUY")
            self.assertTrue(shadow_log_path("XAUUSD", tmp).is_file())
            logs = engine.read_shadow_log()
            self.assertEqual(len(logs), 1)
            self.assertIn("ml_probability", logs[0])
            logger = DecisionLogger("XAUUSD", tmp)
            self.assertEqual(len(logger.read_all()), 1)


class TestIsolation(unittest.TestCase):
    def test_decision_package_no_forbidden_imports(self):
        for path in DECISION_PKG.glob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._assert_safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._assert_safe(node.module)

    def _assert_safe(self, module: str) -> None:
        for prefix in FORBIDDEN_IMPORT_PREFIXES:
            self.assertFalse(
                module.startswith(prefix),
                f"Forbidden import {module} in decision package",
            )

    def test_trading_kernel_import_unchanged(self):
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401

    def test_risk_gate_import_unchanged(self):
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401

    def test_no_execution_dependency_in_decision(self):
        import tradingbot.ml.decision.predictor as pred
        import tradingbot.ml.decision.shadow as sh

        self.assertNotIn("mt5_execution", pred.__name__)
        self.assertNotIn("TradingKernel", dir(sh))


if __name__ == "__main__":
    unittest.main()
