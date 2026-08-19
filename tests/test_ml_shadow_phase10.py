"""Phase 10 ML shadow integration tests (observation only)."""

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

from tradingbot.ml.data.paths import (
    ml_shadow_kernel_decisions_path,
    ml_shadow_metrics_path,
    ml_shadow_report_path,
    ml_shadow_risk_decisions_path,
    ml_shadow_signals_path,
    ml_shadow_virtual_trades_path,
)
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.paper_trading.model_registry import build_test_freeze_contract, freeze_phase9_9_artifacts
from tradingbot.ml.paper_trading.paper_broker import PaperBroker
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.shadow.config import ShadowConfig
from tradingbot.ml.shadow.kernel_bridge import ShadowKernelBridge
from tradingbot.ml.shadow.ml_adapter import MLAdapter
from tradingbot.ml.shadow.shadow_engine import MLShadowEngine
from tradingbot.ml.shadow.shadow_signal import ShadowSignal

SHADOW_PKG = ROOT / "tradingbot" / "ml" / "shadow"
SHADOW_FILES = (
    "__init__.py",
    "config.py",
    "ml_adapter.py",
    "shadow_signal.py",
    "kernel_bridge.py",
    "decision_logger.py",
    "shadow_engine.py",
    "shadow_metrics.py",
)
FORBIDDEN = (
    "order_send",
    "mt5_execution",
    "live_order",
    "trade_request",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.pipeline.execution_stage",
)
TEST_MIN_SAMPLES = 80


def _scan_forbidden() -> list[str]:
    violations: list[str] = []
    for name in SHADOW_FILES:
        path = SHADOW_PKG / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            else:
                continue
            for module in mods:
                for prefix in FORBIDDEN:
                    if prefix in module or module == prefix:
                        violations.append(f"{name}: {module}")
    return violations


def _synthetic_candles(n: int = 200, *, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-06-01", periods=n, freq="5min", tz="UTC")
    closes = 2300.0 + np.cumsum(rng.normal(0, 0.2, n))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + rng.uniform(0.1, 0.8, n),
            "low": closes - rng.uniform(0.1, 0.8, n),
            "close": closes,
            "volume": rng.integers(50, 200, n),
        },
        index=idx,
    )


def _synthetic_source(n: int = 1200, *, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    labels = rng.choice([0, 1], size=n, p=[0.45, 0.55])
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": rng.choice(["order_block", "choch", "fvg", "bos"], size=n),
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "timeframe_role": "entry_execution",
        "entry_price": 2300.0 + rng.normal(0, 1, n),
        "direction": rng.choice([1, -1], size=n),
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": labels,
        "future_window_bars": 72,
        "tp_hit": labels == 1,
        "sl_hit": labels == 0,
        "risk_unit": rng.uniform(2, 8, n),
        "split": "train",
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "volatility_regime": 0.5,
        "trend_strength": 15.0,
        "h4_trend_bias": 0.0,
        "atr_percentile": 45.0,
        "ema_cross_state": 0.0,
        "ema50_slope": 0.0,
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    df = pd.DataFrame(rows)
    n_train = int(n * 0.7)
    n_val = int(n * 0.15)
    df["split"] = ["train"] * n_train + ["validation"] * n_val + ["test"] * (n - n_train - n_val)
    return df


def _setup_shadow(tmp: str) -> str:
    store = DatasetStore(tmp)
    raw = _synthetic_source()
    store.store("XAUUSD", "M5", raw)
    store.store_v2("XAUUSD", "M5", raw)
    CandleStore(tmp).store("XAUUSD", "M5", _synthetic_candles())
    v2 = store.load_v2("XAUUSD", "M5")
    assert v2 is not None
    contract = build_test_freeze_contract()
    freeze_phase9_9_artifacts(v2, contract=contract, base_dir=tmp, seed=42)
    return dataset_content_fingerprint(v2)


class TestPhase10MLShadow(unittest.TestCase):
    def test_forbidden_imports_zero(self):
        self.assertEqual(_scan_forbidden(), [])

    def test_model_load_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            adapter = MLAdapter.load(base_dir=tmp)
            validation = adapter.validate(dataset_df=df)
            self.assertTrue(validation.passed)

    def test_ml_adapter_signal_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            ml = MLAdapter.load(base_dir=tmp)
            self.assertEqual(ml._direction(0.55), "BUY")
            self.assertEqual(ml._direction(0.45), "SELL")
            self.assertEqual(ml._direction(0.50), "HOLD")

    def test_shadow_signal_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            ml = MLAdapter.load(base_dir=tmp)
            pred = ml.predict(
                {f: 0.0 for f in ml.bundle.feature_order},
                timestamp="2024-01-01T00:00:00+00:00",
            )
            sig = ShadowSignal.from_prediction(pred, symbol="XAUUSD", timeframe="M5", model_version="phase9_9_best")
            payload = sig.to_dict()
            self.assertIn("features_hash", payload)
            self.assertEqual(payload["model_version"], "phase9_9_best")

    def test_kernel_bridge_risk_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _synthetic_candles()
            bridge = ShadowKernelBridge(legacy_config={"INITIAL_BALANCE": 10_000, "RISK_PER_TRADE": 0.005})
            shadow = ShadowSignal(
                timestamp="t",
                symbol="XAUUSD",
                timeframe="M5",
                direction="BUY",
                probability=0.6,
                confidence=0.2,
                model_version="phase9_9_best",
                features_hash="abc",
            )
            decision = bridge.evaluate(shadow, candles, 100)
            self.assertIn("risk_result", decision)
            self.assertIn("kernel_result", decision)
            self.assertIsNotNone(decision["virtual_sl"])

    def test_broker_tp_sl_simulation(self):
        broker = PaperBroker()
        bar = pd.Series({"high": 2325.0, "low": 2295.0})
        hit = broker.resolve_bar(bar, direction=1, stop_loss=2290.0, take_profit=2320.0)
        self.assertEqual(hit[0], "TP")

    def test_shadow_run_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            cfg = ShadowConfig(symbol="XAUUSD", timeframe="M5", shadow_days=30, mode="replay")
            result = MLShadowEngine(base_dir=tmp).run(cfg, run_id="run_v1")
            self.assertTrue(ml_shadow_signals_path("run_v1", tmp).is_file())
            self.assertTrue(ml_shadow_kernel_decisions_path("run_v1", tmp).is_file())
            self.assertTrue(ml_shadow_risk_decisions_path("run_v1", tmp).is_file())
            self.assertTrue(ml_shadow_virtual_trades_path("run_v1", tmp).is_file())
            self.assertTrue(ml_shadow_metrics_path("run_v1", tmp).is_file())
            self.assertTrue(ml_shadow_report_path("run_v1", tmp).is_file())
            report = json.loads(ml_shadow_report_path("run_v1", tmp).read_text())
            self.assertFalse(report.get("order_send", True))
            self.assertEqual(result.status, "PASS")

    def test_no_dataset_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp = _setup_shadow(tmp)
            cfg = ShadowConfig(shadow_days=30)
            MLShadowEngine(base_dir=tmp).run(cfg, run_id="run_mut")
            fp2 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp, fp2)

    def test_sequential_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            MLShadowEngine(base_dir=tmp).run(ShadowConfig(shadow_days=30), run_id="run_seq")
            signals = json.loads(ml_shadow_signals_path("run_seq", tmp).read_text())
            ts_list = [s["timestamp"] for s in signals]
            self.assertEqual(ts_list, sorted(ts_list))

    def test_report_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            engine = MLShadowEngine(base_dir=tmp)
            engine.run(ShadowConfig(shadow_days=30), run_id="run_report")
            report = engine.report_only("run_report")
            self.assertIn("metrics", report)

    def test_metrics_ml_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            MLShadowEngine(base_dir=tmp).run(ShadowConfig(shadow_days=30), run_id="run_metrics")
            metrics = json.loads(ml_shadow_metrics_path("run_metrics", tmp).read_text())
            total = metrics["ml_buy_count"] + metrics["ml_sell_count"] + metrics["ml_hold_count"]
            self.assertEqual(total, metrics["ml_total_signals"])
            self.assertGreater(metrics["ml_total_signals"], 0)

    def test_dataset_fallback_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DatasetStore(tmp)
            raw = _synthetic_source()
            store.store("XAUUSD", "M5", raw)
            store.store_v2("XAUUSD", "M5", raw)
            v2 = store.load_v2("XAUUSD", "M5")
            assert v2 is not None
            contract = build_test_freeze_contract()
            freeze_phase9_9_artifacts(v2, contract=contract, base_dir=tmp)
            result = MLShadowEngine(base_dir=tmp).run(ShadowConfig(shadow_days=30), run_id="run_fb")
            self.assertGreater(result.num_signals, 0)

    def test_decision_record_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            MLShadowEngine(base_dir=tmp).run(ShadowConfig(shadow_days=30), run_id="run_dec")
            signals = json.loads(ml_shadow_signals_path("run_dec", tmp).read_text())
            risks = json.loads(ml_shadow_risk_decisions_path("run_dec", tmp).read_text())
            self.assertGreater(len(signals), 0)
            self.assertEqual(len(risks), len(signals))
            self.assertIn("allowed", risks[0])

    def test_feature_order_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            adapter = MLAdapter.load(base_dir=tmp)
            self.assertEqual(
                adapter.bundle.feature_order,
                ["ema50_slope", "candle_direction", "structure_distance"],
            )

    def test_shadow_config_from_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_shadow(tmp)
            adapter = MLAdapter.load(base_dir=tmp)
            cfg = ShadowConfig.from_bundle_config(adapter.bundle.config, symbol="XAUUSD")
            self.assertAlmostEqual(cfg.buy_threshold, 0.55)
            self.assertAlmostEqual(cfg.risk_pct, 0.005)


if __name__ == "__main__":
    unittest.main()
