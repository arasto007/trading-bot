"""Phase 10.4 shadow monitoring tests (offline)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import (
    ml_shadow_monitor_checkpoint_path,
    ml_shadow_monitor_final_report_path,
    phase10_4_stability_report_path,
)
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast
from tradingbot.ml.monitoring.anomaly_detector import AnomalyDetector, AnomalyReport
from tradingbot.ml.monitoring.long_run_manager import LongRunConfig, LongRunManager
from tradingbot.ml.monitoring.session_report import save_monitor_session
from tradingbot.ml.monitoring.shadow_monitor import ShadowMonitor
from tradingbot.ml.monitoring.stability_analyzer import StabilityAnalyzer
from tradingbot.ml.paper_trading.model_registry import build_test_freeze_contract, freeze_phase9_9_artifacts

MONITORING_PKG = ROOT / "tradingbot" / "ml" / "monitoring"


def _candles(n: int = 250) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-06-01", periods=n, freq="5min", tz="UTC")
    closes = 2300.0 + np.cumsum(rng.normal(0, 0.2, n))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": rng.integers(50, 200, n),
        },
        index=idx,
    )


def _dataset(n: int = 1200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": rng.choice(["order_block", "choch", "fvg", "bos"], size=n),
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "entry_price": 2300.0 + rng.normal(0, 1, n),
        "direction": rng.choice([1, -1], size=n),
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": rng.choice([0, 1], size=n),
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
    return pd.DataFrame(rows)


def _setup(tmp: str) -> pd.DataFrame:
    candles = _candles()
    CandleStore(tmp).store("XAUUSD", "M5", candles)
    store = DatasetStore(tmp)
    raw = _dataset()
    store.store_v2("XAUUSD", "M5", raw)
    freeze_phase9_9_artifacts(raw, contract=build_test_freeze_contract(), base_dir=tmp, seed=42)
    return candles


class TestPhase104Monitoring(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["ENABLE_ML_SHADOW"] = "true"
        os.environ["ML_SHADOW_MODE"] = "true"

    def test_monitor_starts_and_collects(self):
        monitor = ShadowMonitor(run_id="t1", symbol="XAUUSD", timeframe="M5")
        monitor.on_cycle(
            event={
                "timestamp": "2024-06-01T10:00:00+00:00",
                "ml_signal": "SELL",
                "ml_probability": 0.4,
                "risk_allowed": True,
                "execution_status": "shadow_blocked",
            },
            context={"has_signal": True, "errors": []},
            ml_meta={"ml_direction": "SELL", "ml_probability": 0.4},
            bar_index=100,
        )
        self.assertEqual(monitor.kernel_cycles, 1)
        self.assertEqual(monitor.ml_sell, 1)

    def test_metrics_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_monitor_session(
                "persist_test",
                config={"phase": "10.4"},
                hourly_metrics=[{"hour": "h1", "cycles": 1}],
                signals_summary={"ml_buy": 1},
                risk_summary={"risk_allowed": 1},
                trade_quality=[],
                anomalies={"warnings": []},
                equity_curve=[],
                final_report={"decision": {"decision": "PASS"}},
                base_dir=tmp,
                write_global_stability=False,
            )
            self.assertTrue(ml_shadow_monitor_final_report_path("persist_test", tmp).is_file())
            self.assertTrue(paths["run_dir"].is_dir())

    def test_ast_safety_scan(self):
        self.assertEqual(scan_live_shadow_ast(), [])

    def test_no_execution_path_in_monitoring(self):
        import ast

        forbidden_calls = {"order_send", "positions_get"}
        forbidden_modules = {"mt5_execution", "Mt5ExecutionAdapter"}
        for name in MONITORING_PKG.glob("*.py"):
            tree = ast.parse(name.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for token in forbidden_modules:
                            self.assertNotIn(token, alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for token in forbidden_modules:
                        self.assertNotIn(token, node.module)
                elif isinstance(node, ast.Call):
                    func = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                    self.assertNotIn(func, forbidden_calls)

    def test_trade_integrity_validation_detects_bad_trade(self):
        detector = AnomalyDetector()
        report = AnomalyReport()
        detector.check_trade_integrity(
            [{"entry": 2300.0, "sl": 2300.0, "tp": 2320.0, "timestamp": "t"}],
            invalid_count=0,
            report=report,
        )
        self.assertTrue(any(c["code"] == "entry_equals_sl" for c in report.critical))

    def test_probability_drift_detection(self):
        detector = AnomalyDetector()
        report = AnomalyReport()
        probs = [0.9] * 50
        detector.check_probability_drift(probs, report)
        self.assertTrue(any(c["code"] == "probability_drift" for c in report.warnings))

    def test_feature_drift_detection(self):
        detector = AnomalyDetector()
        report = AnomalyReport()
        samples = {"ema50_slope": [10.0] * 30, "candle_direction": [0.0] * 30, "structure_distance": [0.0] * 30}
        detector.check_feature_drift(samples, report)
        self.assertTrue(any(c["code"] == "feature_drift" for c in report.warnings))

    def test_signal_collapse_detection(self):
        detector = AnomalyDetector()
        report = AnomalyReport()
        detector.check_signal_collapse(0, 0, 1000, report)
        self.assertTrue(any(c["code"] == "signal_collapse" for c in report.warnings))

    def test_checkpoint_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = ShadowMonitor(run_id="resume_test", symbol="XAUUSD", timeframe="M5", base_dir=tmp)
            monitor.last_bar_index = 150
            monitor.save_checkpoint()
            loaded = ShadowMonitor.load_checkpoint("resume_test", tmp)
            assert loaded is not None
            self.assertEqual(loaded["last_bar_index"], 150)

    def test_deterministic_reports(self):
        analyzer = StabilityAnalyzer()
        metrics = {
            "profit_factor": 1.2,
            "expectancy_r": 0.1,
            "max_drawdown": 0.05,
            "execution_blocked": 5,
            "risk_allowed": 5,
        }
        _, v1 = analyzer.analyze(
            metrics=metrics,
            ml_buy=2,
            ml_sell=3,
            ml_hold=90,
            probabilities=[0.5] * 30,
            feature_samples={"ema50_slope": [0.1] * 30, "candle_direction": [0.0] * 30, "structure_distance": [0.0] * 30},
            virtual_trades=[{"entry": 2300, "sl": 2290, "tp": 2320, "timestamp": "t"}],
            invalid_trade_count=0,
            pipeline_errors=0,
        )
        _, v2 = analyzer.analyze(
            metrics=metrics,
            ml_buy=2,
            ml_sell=3,
            ml_hold=90,
            probabilities=[0.5] * 30,
            feature_samples={"ema50_slope": [0.1] * 30, "candle_direction": [0.0] * 30, "structure_distance": [0.0] * 30},
            virtual_trades=[{"entry": 2300, "sl": 2290, "tp": 2320, "timestamp": "t"}],
            invalid_trade_count=0,
            pipeline_errors=0,
        )
        self.assertEqual(v1.decision, v2.decision)

    def test_long_run_manager_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = LongRunConfig(
                run_id="monitor_offline",
                shadow_days=7,
                skip_preflight=True,
                candles_df=candles,
            )
            result = LongRunManager(base_dir=tmp).run(cfg)
            self.assertIn(result.decision, ("PASS", "NEEDS REVIEW"))
            self.assertTrue(ml_shadow_monitor_final_report_path("monitor_offline", tmp).is_file())

    def test_global_stability_report_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_monitor_session(
                "global_test",
                config={},
                hourly_metrics=[],
                signals_summary={},
                risk_summary={},
                trade_quality=[],
                anomalies={},
                equity_curve=[],
                final_report={"decision": {"decision": "PASS"}},
                base_dir=tmp,
                write_global_stability=True,
            )
            self.assertTrue(phase10_4_stability_report_path(tmp).is_file())


if __name__ == "__main__":
    unittest.main()
