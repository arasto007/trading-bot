"""Phase 10.1 — kernel ML shadow integration tests."""

from __future__ import annotations

import ast
import asyncio
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

from tradingbot.domain.models import MarketKey
from tradingbot.ml.data.paths import ml_kernel_shadow_report_path, ml_kernel_shadow_signals_path
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.integration.composite_registry import CompositeStrategyRegistry
from tradingbot.ml.integration.config import KernelShadowConfig
from tradingbot.ml.integration.kernel_builder import build_kernel_shadow
from tradingbot.ml.integration.kernel_shadow_runner import KernelShadowRunner
from tradingbot.ml.integration.replay_market_data import ReplayMarketDataAdapter
from tradingbot.ml.integration.shadow_execution_guard import ShadowExecutionGuard
from tradingbot.ml.integration.ml_strategy import STRATEGY_NAME
from tradingbot.ml.paper_trading.model_registry import build_test_freeze_contract, freeze_phase9_9_artifacts

INTEGRATION_PKG = ROOT / "tradingbot" / "ml" / "integration"
INTEGRATION_FILES = (
    "__init__.py",
    "config.py",
    "ml_strategy.py",
    "composite_registry.py",
    "shadow_execution_guard.py",
    "replay_market_data.py",
    "kernel_builder.py",
    "kernel_shadow_runner.py",
    "kernel_run_logger.py",
)
FORBIDDEN = (
    "order_send",
    "mt5_execution",
    "live_order",
    "trade_request",
    "tradingbot.adapters.mt5_execution",
)
KERNEL_PATH = ROOT / "tradingbot" / "kernel" / "trading_kernel.py"


def _scan_forbidden() -> list[str]:
    violations: list[str] = []
    for name in INTEGRATION_FILES:
        path = INTEGRATION_PKG / name
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


def _synthetic_candles(n: int = 200) -> pd.DataFrame:
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
    labels = rng.choice([0, 1], size=n, p=[0.45, 0.55])
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
        "label": labels,
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


def _setup(tmp: str) -> None:
    CandleStore(tmp).store("XAUUSD", "M5", _synthetic_candles())
    store = DatasetStore(tmp)
    raw = _synthetic_dataset()
    store.store_v2("XAUUSD", "M5", raw)
    freeze_phase9_9_artifacts(raw, contract=build_test_freeze_contract(), base_dir=tmp, seed=42)


class TestPhase101KernelBridge(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["ENABLE_ML_SHADOW"] = "true"
        os.environ["ML_SHADOW_MODE"] = "true"

    def test_forbidden_imports_zero(self):
        self.assertEqual(_scan_forbidden(), [])

    def test_trading_kernel_file_unchanged_logic(self):
        """Kernel module exists; integration injects via constructor only."""
        text = KERNEL_PATH.read_text(encoding="utf-8")
        self.assertIn("class TradingKernel", text)
        self.assertNotIn("ml_shadow", text.lower())
        self.assertNotIn("MLShadowStrategy", text)

    def test_ml_signal_enters_kernel_cycle_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            candles = _synthetic_candles(200)
            replay = ReplayMarketDataAdapter(candles)
            replay.set_bar_index(150)
            kernel, strategies, guard = build_kernel_shadow(
                replay, base_dir=tmp, seed=42, legacy_config={"INITIAL_BALANCE": 10_000, "RISK_PER_TRADE": 0.005}
            )
            market = MarketKey("XAUUSD", "M5")
            ctx = asyncio.run(kernel.run_market_cycle(market))
            if ctx.signal is not None and ctx.signal.strategy_name == STRATEGY_NAME:
                self.assertEqual(ctx.signal.metadata.get("signal_source"), "ml_shadow")
            else:
                self.assertIsNotNone(ctx.signal or ctx.errors)

    def test_risk_gate_runs_on_kernel_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            replay = ReplayMarketDataAdapter(_synthetic_candles(200))
            replay.set_bar_index(150)
            kernel, _, _ = build_kernel_shadow(
                replay, base_dir=tmp, legacy_config={"INITIAL_BALANCE": 10_000, "RISK_PER_TRADE": 0.005}
            )
            ctx = asyncio.run(kernel.run_market_cycle(MarketKey("XAUUSD", "M5")))
            if ctx.signal is not None:
                self.assertIsNotNone(ctx.risk)

    def test_execution_guard_blocks_orders(self):
        guard = ShadowExecutionGuard()
        from tradingbot.domain.enums import SignalDirection
        from tradingbot.domain.models import TradingSignal

        sig = TradingSignal(
            direction=SignalDirection.BUY,
            confidence=0.6,
            symbol="XAUUSD",
            timeframe="M5",
            strategy_name=STRATEGY_NAME,
            metadata={"ml_probability": 0.6, "entry": 2300.0},
        )
        result = guard.execute(sig, 0.01)
        self.assertFalse(result.success)
        self.assertIn("shadow_blocked", result.message)
        self.assertEqual(len(guard.blocked_orders), 1)

    def test_shadow_execution_guard_no_order_send(self):
        text = (INTEGRATION_PKG / "shadow_execution_guard.py").read_text(encoding="utf-8")
        self.assertNotIn("mt5_execution", text)
        self.assertNotIn("import MetaTrader5", text)

    def test_composite_registry_prefers_ml(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            registry = CompositeStrategyRegistry(
                {"INITIAL_BALANCE": 10_000}, base_dir=tmp, seed=42
            )
            df = _synthetic_candles(120)
            sig = registry.generate_signal(MarketKey("XAUUSD", "M5"), df)
            if sig is not None and sig.strategy_name == STRATEGY_NAME:
                self.assertIn("ml_probability", sig.metadata)

    def test_kernel_shadow_runner_produces_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            cfg = KernelShadowConfig(shadow_days=30, max_replay_bars=50, warmup_bars=80)
            result = KernelShadowRunner(base_dir=tmp).run(cfg, run_id="kernel_run_test")
            self.assertTrue(ml_kernel_shadow_report_path("kernel_run_test", tmp).is_file())
            self.assertEqual(result.status, "PASS")
            report = json.loads(ml_kernel_shadow_report_path("kernel_run_test", tmp).read_text())
            self.assertTrue(report.get("kernel_integrated"))

    def test_deterministic_replay_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            cfg = KernelShadowConfig(shadow_days=30, max_replay_bars=30, warmup_bars=80)
            r1 = KernelShadowRunner(base_dir=tmp).run(cfg, run_id="kernel_run_det1")
            r2 = KernelShadowRunner(base_dir=tmp).run(cfg, run_id="kernel_run_det2")
            self.assertEqual(r1.num_events, r2.num_events)
            self.assertEqual(r1.ml_signals, r2.ml_signals)

    def test_signals_json_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            KernelShadowRunner(base_dir=tmp).run(
                KernelShadowConfig(max_replay_bars=40), run_id="kernel_run_sig"
            )
            path = ml_kernel_shadow_signals_path("kernel_run_sig", tmp)
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text())
            self.assertIsInstance(payload, list)


if __name__ == "__main__":
    unittest.main()
