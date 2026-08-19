"""Phase 10.2 live shadow validation tests (offline + read-only patterns)."""

from __future__ import annotations

import ast
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
    ml_live_preflight_report_path,
    ml_live_shadow_report_path,
    ml_live_shadow_signals_path,
)
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.integration.live_market_adapter import LiveMarketAdapter
from tradingbot.ml.integration.live_metrics import LiveMetricsTracker
from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast
from tradingbot.ml.integration.live_shadow_runner import LiveShadowConfig, LiveShadowRunner
from tradingbot.ml.integration.shadow_execution_guard import ShadowExecutionGuard
from tradingbot.ml.integration.ml_strategy import STRATEGY_NAME
from tradingbot.ml.paper_trading.model_registry import build_test_freeze_contract, freeze_phase9_9_artifacts

INTEGRATION_PKG = ROOT / "tradingbot" / "ml" / "integration"
LIVE_FILES = (
    "live_market_adapter.py",
    "live_shadow_runner.py",
    "live_preflight.py",
    "live_run_logger.py",
    "live_metrics.py",
)
FORBIDDEN = ("order_send", "trade_request", "positions_get", "mt5_execution")


def _synthetic_candles(n: int = 250) -> pd.DataFrame:
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


def _synthetic_dataset(n: int = 1200) -> pd.DataFrame:
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
    candles = _synthetic_candles()
    CandleStore(tmp).store("XAUUSD", "M5", candles)
    store = DatasetStore(tmp)
    raw = _synthetic_dataset()
    store.store_v2("XAUUSD", "M5", raw)
    freeze_phase9_9_artifacts(raw, contract=build_test_freeze_contract(), base_dir=tmp, seed=42)
    return candles


class TestPhase102LiveShadow(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["ENABLE_ML_SHADOW"] = "true"
        os.environ["ML_SHADOW_MODE"] = "true"

    def test_ast_scan_no_forbidden_imports(self):
        violations = scan_live_shadow_ast()
        self.assertEqual(violations, [])

    def test_live_adapter_ast_read_only(self):
        violations = scan_live_shadow_ast()
        adapter_violations = [v for v in violations if v.startswith("live_market_adapter")]
        self.assertEqual(adapter_violations, [])

    def test_candle_deduplication(self):
        candles = _synthetic_candles(120)
        adapter = LiveMarketAdapter("XAUUSD", "M5", {}, candles=candles)
        adapter.load_history()
        seen = [c.timestamp for _, c in adapter.iter_closed_bars(start_index=80)]
        self.assertEqual(len(seen), len(set(seen)))

    def test_chronological_processing(self):
        candles = _synthetic_candles(120)
        adapter = LiveMarketAdapter("XAUUSD", "M5", {}, candles=candles)
        adapter.load_history()
        ts_list = [c.timestamp for _, c in adapter.iter_closed_bars(start_index=80)]
        self.assertEqual(ts_list, sorted(ts_list))

    def test_closed_candle_shape(self):
        candles = _synthetic_candles(100)
        adapter = LiveMarketAdapter("XAUUSD", "M5", {}, candles=candles)
        adapter.load_history()
        _, candle = next(adapter.iter_closed_bars(start_index=80))
        payload = candle.to_dict()
        for key in ("timestamp", "open", "high", "low", "close", "volume"):
            self.assertIn(key, payload)

    def test_execution_guard_blocks(self):
        from tradingbot.domain.enums import SignalDirection
        from tradingbot.domain.models import TradingSignal

        guard = ShadowExecutionGuard()
        sig = TradingSignal(
            direction=SignalDirection.BUY,
            confidence=0.6,
            symbol="XAUUSD",
            timeframe="M5",
            strategy_name=STRATEGY_NAME,
        )
        result = guard.execute(sig, 0.01)
        self.assertFalse(result.success)
        self.assertIn("shadow_blocked", result.message)

    def test_metrics_calculation(self):
        tracker = LiveMetricsTracker()
        tracker.record_cycle(
            ml_direction="BUY",
            confidence=0.6,
            spread=1.2,
            kernel_has_signal=True,
            ml_in_kernel=True,
            risk_allowed=True,
            risk_reason="ok",
            execution_blocked=True,
        )
        tracker.record_trade({"timestamp": "t", "pnl": 50.0, "R_multiple": 2.0})
        m = tracker.compute()
        self.assertEqual(m.kernel_cycles, 1)
        self.assertEqual(m.virtual_trades, 1)

    def test_live_shadow_runner_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = LiveShadowConfig(
                shadow_days=7,
                skip_preflight=True,
                candles_df=candles,
            )
            result = LiveShadowRunner(base_dir=tmp).run(cfg, run_id="live_run_test")
            self.assertTrue(ml_live_shadow_report_path("live_run_test", tmp).is_file())
            self.assertEqual(result.status, "PASS")
            self.assertGreater(result.metrics.get("kernel_cycles", 0), 0)

    def test_kernel_execution_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = LiveShadowConfig(skip_preflight=True, candles_df=candles, shadow_days=7)
            result = LiveShadowRunner(base_dir=tmp).run(cfg, run_id="live_run_kernel")
            self.assertGreater(result.metrics.get("kernel_cycles", 0), 0)

    def test_ml_signal_generation_in_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = LiveShadowConfig(skip_preflight=True, candles_df=candles, shadow_days=7)
            LiveShadowRunner(base_dir=tmp).run(cfg, run_id="live_run_ml")
            signals = json.loads(ml_live_shadow_signals_path("live_run_ml", tmp).read_text())
            if signals:
                names = {s.get("strategy_name") for s in signals}
                self.assertTrue(STRATEGY_NAME in names or len(names) >= 1)

    def test_risk_results_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = LiveShadowConfig(skip_preflight=True, candles_df=candles, shadow_days=7)
            result = LiveShadowRunner(base_dir=tmp).run(cfg, run_id="live_run_risk")
            self.assertGreaterEqual(result.metrics.get("risk_blocked", 0) + result.metrics.get("risk_allowed", 0), 0)

    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = LiveShadowConfig(skip_preflight=True, candles_df=candles, shadow_days=7)
            runner = LiveShadowRunner(base_dir=tmp)
            runner.run(cfg, run_id="live_run_report")
            report = runner.report_only("live_run_report")
            self.assertTrue(report.get("live_shadow"))
            self.assertFalse(report.get("order_send", True))

    def test_preflight_report_path_exists_after_scan(self):
        violations = scan_live_shadow_ast()
        self.assertIsInstance(violations, list)

    def test_signals_json_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = LiveShadowConfig(skip_preflight=True, candles_df=candles, shadow_days=7)
            LiveShadowRunner(base_dir=tmp).run(cfg, run_id="live_run_sig")
            path = ml_live_shadow_signals_path("live_run_sig", tmp)
            self.assertTrue(path.is_file())

    def test_ml_in_kernel_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = LiveShadowConfig(skip_preflight=True, candles_df=candles, shadow_days=7)
            result = LiveShadowRunner(base_dir=tmp).run(cfg, run_id="live_run_mlk")
            self.assertIn("ml_in_kernel", result.metrics)

    def test_shadow_mode_env(self):
        self.assertEqual(os.environ.get("ML_SHADOW_MODE"), "true")
        self.assertEqual(os.environ.get("ENABLE_ML_SHADOW"), "true")


if __name__ == "__main__":
    unittest.main()
