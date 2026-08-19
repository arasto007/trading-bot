"""Phase 12 — controlled live pilot tests."""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import ExecutionResult, TradingSignal
from tradingbot.ml.live_pilot.config import (
    PilotConfig,
    ab_signals,
    apply_mode_env,
    is_pilot_live_enabled,
    resolve_mode,
    session_for_hour,
    signal_from_probability,
)
from tradingbot.ml.live_pilot.execution_guard import PilotExecutionGuard, create_mt5_executor
from tradingbot.ml.live_pilot.health_check import run_health_check, scan_phase12_ast
from tradingbot.ml.live_pilot.kill_switch import PilotKillSwitch
from tradingbot.ml.live_pilot.live_controller import LiveController, classify_pilot_regime
from tradingbot.ml.live_pilot.position_limiter import PositionLimiter
from tradingbot.ml.live_pilot.safety_manager import SafetyManager
from tradingbot.ml.live_pilot.trade_journal import TradeJournal
from tradingbot.ml.paper.config import validate_frozen_model

LIVE_PILOT_PKG = ROOT / "tradingbot" / "ml" / "live_pilot"


def _signal(**kwargs) -> TradingSignal:
    defaults = dict(
        direction=SignalDirection.BUY,
        confidence=0.6,
        symbol="XAUUSD",
        timeframe="M5",
        strategy_name="ml_shadow_phase9_9",
        stop_loss=2300.0,
        take_profit=2320.0,
        metadata={"bar_timestamp": "2026-06-01T10:00:00+00:00", "ml_probability": 0.58, "entry": 2310.0},
    )
    defaults.update(kwargs)
    return TradingSignal(**defaults)


class TestPhase12Config(unittest.TestCase):
    def test_default_mode_shadow(self):
        self.assertEqual(resolve_mode(None), "SHADOW")

    def test_ab_signals_strategy_a_and_b(self):
        ab = ab_signals(0.52)
        self.assertEqual(ab["strategy_a"], "HOLD")
        self.assertEqual(ab["strategy_b"], "BUY")

    def test_signal_from_probability(self):
        self.assertEqual(signal_from_probability(0.56, buy=0.55, sell=0.45), "BUY")
        self.assertEqual(signal_from_probability(0.35, buy=0.55, sell=0.45), "SELL")

    def test_pilot_not_enabled_by_default(self):
        os.environ.pop("ENABLE_PHASE12_LIVE", None)
        os.environ.pop("PILOT_APPROVAL", None)
        self.assertFalse(is_pilot_live_enabled())

    def test_pilot_enabled_with_dual_env(self):
        os.environ["ENABLE_PHASE12_LIVE"] = "true"
        os.environ["PILOT_APPROVAL"] = "true"
        self.assertTrue(is_pilot_live_enabled())
        os.environ.pop("ENABLE_PHASE12_LIVE", None)
        os.environ.pop("PILOT_APPROVAL", None)

    def test_apply_mode_shadow_sets_dry_run(self):
        apply_mode_env("SHADOW")
        self.assertEqual(os.environ.get("ML_SHADOW_MODE"), "true")
        self.assertEqual(os.environ.get("TRADINGBOT_DRY_RUN"), "1")

    def test_session_for_hour(self):
        self.assertIn("asia", session_for_hour(3))
        self.assertIn("london", session_for_hour(10))


class TestPhase12KillSwitch(unittest.TestCase):
    def setUp(self):
        self.ks = PilotKillSwitch()

    def test_kill_switch_daily_loss(self):
        self.ks.check_daily_loss(0.03, 0.02)
        self.assertTrue(self.ks.active)
        self.assertIn("daily_loss", self.ks.reason)

    def test_kill_switch_spread(self):
        self.ks.check_spread(15.0, 8.0)
        self.assertTrue(self.ks.active)

    def test_kill_switch_connection(self):
        self.ks.check_connection(False)
        self.assertTrue(self.ks.active)

    def test_kill_switch_checksum(self):
        self.ks.check_checksum(False)
        self.assertTrue(self.ks.active)


class TestPhase12PositionLimiter(unittest.TestCase):
    def test_max_open_positions(self):
        pl = PositionLimiter(max_open_positions=1, max_trades_per_day=10)
        pl.record_entry()
        ok, reason = pl.can_open_position()
        self.assertFalse(ok)
        self.assertEqual(reason, "max_open_positions")

    def test_max_trades_per_day(self):
        pl = PositionLimiter(max_open_positions=5, max_trades_per_day=2)
        pl.record_entry()
        pl.record_exit(won=True)
        pl.record_entry()
        pl.record_exit(won=True)
        ok, reason = pl.can_open_position()
        self.assertFalse(ok)
        self.assertEqual(reason, "max_trades_per_day")

    def test_consecutive_losses(self):
        pl = PositionLimiter(max_consecutive_losses=3)
        pl.record_entry()
        pl.record_exit(won=False)
        pl.record_entry()
        pl.record_exit(won=False)
        pl.record_entry()
        pl.record_exit(won=False)
        ok, reason = pl.can_open_position()
        self.assertFalse(ok)
        self.assertEqual(reason, "max_consecutive_losses")


class TestPhase12SafetyManager(unittest.TestCase):
    def test_shadow_mode_blocks_live(self):
        cfg = PilotConfig(mode="SHADOW")
        sm = SafetyManager(cfg, model_checksum_valid=True)
        result = sm.validate_pre_order(_signal(), lot=0.01)
        self.assertFalse(result.allowed)
        self.assertIn("shadow", result.reason)

    def test_pilot_without_approval_blocked(self):
        os.environ.pop("ENABLE_PHASE12_LIVE", None)
        os.environ.pop("PILOT_APPROVAL", None)
        cfg = PilotConfig(mode="PILOT")
        sm = SafetyManager(cfg, model_checksum_valid=True)
        result = sm.validate_pre_order(_signal(), lot=0.01, mt5_connected=True)
        self.assertFalse(result.allowed)

    def test_invalid_sl_tp_rejected(self):
        os.environ["ENABLE_PHASE12_LIVE"] = "true"
        os.environ["PILOT_APPROVAL"] = "true"
        apply_mode_env("PILOT")
        cfg = PilotConfig(mode="PILOT")
        sm = SafetyManager(cfg, model_checksum_valid=True)
        sig = _signal(stop_loss=None, take_profit=None)
        result = sm.validate_pre_order(sig, lot=0.01, mt5_connected=True)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "invalid_sl_tp")
        os.environ.pop("ENABLE_PHASE12_LIVE", None)
        os.environ.pop("PILOT_APPROVAL", None)

    def test_invalid_volume_rejected(self):
        os.environ["ENABLE_PHASE12_LIVE"] = "true"
        os.environ["PILOT_APPROVAL"] = "true"
        apply_mode_env("PILOT")
        cfg = PilotConfig(mode="PILOT")
        sm = SafetyManager(cfg, model_checksum_valid=True)
        result = sm.validate_pre_order(_signal(), lot=0.0, mt5_connected=True)
        self.assertFalse(result.allowed)
        os.environ.pop("ENABLE_PHASE12_LIVE", None)
        os.environ.pop("PILOT_APPROVAL", None)

    def test_spread_protection(self):
        cfg = PilotConfig(mode="PILOT", max_spread_pips=5.0)
        sm = SafetyManager(cfg, model_checksum_valid=True)
        os.environ["ENABLE_PHASE12_LIVE"] = "true"
        os.environ["PILOT_APPROVAL"] = "true"
        apply_mode_env("PILOT")
        result = sm.validate_pre_order(_signal(), lot=0.01, spread_pips=10.0, mt5_connected=True)
        self.assertFalse(result.allowed)
        self.assertTrue(sm.kill_switch.active)
        os.environ.pop("ENABLE_PHASE12_LIVE", None)
        os.environ.pop("PILOT_APPROVAL", None)

    def test_regime_filter_block(self):
        cfg = PilotConfig(mode="PILOT", regime_filter_block=True)
        sm = SafetyManager(cfg, model_checksum_valid=True)
        os.environ["ENABLE_PHASE12_LIVE"] = "true"
        os.environ["PILOT_APPROVAL"] = "true"
        apply_mode_env("PILOT")
        result = sm.validate_pre_order(
            _signal(), lot=0.01, mt5_connected=True, regime="HIGH_VOLATILITY"
        )
        self.assertFalse(result.allowed)
        os.environ.pop("ENABLE_PHASE12_LIVE", None)
        os.environ.pop("PILOT_APPROVAL", None)


class TestPhase12ExecutionGuard(unittest.TestCase):
    def test_no_accidental_live_in_shadow(self):
        cfg = PilotConfig(mode="SHADOW")
        sm = SafetyManager(cfg, model_checksum_valid=True)
        inner = MagicMock()
        guard = PilotExecutionGuard(inner, safety=sm)
        result = guard.execute(_signal(), 0.01)
        self.assertFalse(result.success)
        inner.execute.assert_not_called()

    def test_execution_logging_on_success(self):
        os.environ["ENABLE_PHASE12_LIVE"] = "true"
        os.environ["PILOT_APPROVAL"] = "true"
        apply_mode_env("PILOT")
        with tempfile.TemporaryDirectory() as tmp:
            journal = TradeJournal("v1", base_dir=tmp)
            cfg = PilotConfig(mode="PILOT", run_id="v1")
            sm = SafetyManager(cfg, model_checksum_valid=True)
            inner = MagicMock()
            inner.execute.return_value = ExecutionResult(success=True, ticket=12345, message="ok")
            guard = PilotExecutionGuard(inner, safety=sm, journal=journal)
            result = guard.execute(_signal(), 0.01)
            self.assertTrue(result.success)
            self.assertEqual(guard.stats["success"], 1)
            paths = journal.flush()
            self.assertTrue(Path(paths["execution"]).is_file())
        os.environ.pop("ENABLE_PHASE12_LIVE", None)
        os.environ.pop("PILOT_APPROVAL", None)


class TestPhase12AST(unittest.TestCase):
    def test_order_send_only_in_execution_guard(self):
        violations = scan_phase12_ast()
        self.assertEqual(violations, [], msg=f"AST violations: {violations}")

    def test_no_kernel_imports_in_live_pilot(self):
        for py in LIVE_PILOT_PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(
                        node.module.startswith("tradingbot.kernel"),
                        msg=f"{py.name} imports kernel",
                    )

    def test_forbidden_imports_outside_guard(self):
        violations = scan_phase12_ast()
        self.assertEqual(violations, [], msg=f"AST violations: {violations}")


class TestPhase12ModelAndJournal(unittest.TestCase):
    def test_model_loading_validation(self):
        if not (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
            self.skipTest("phase9_9 artifacts missing")
        report = validate_frozen_model()
        self.assertEqual(report["status"], "PASS")

    def test_trade_journal_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TradeJournal("test_run", base_dir=tmp)
            journal.write_config({"phase": "12"})
            journal.log_signal({"test": True})
            paths = journal.flush()
            self.assertTrue(Path(paths["signals"]).is_file())


class TestPhase12HealthCheck(unittest.TestCase):
    def test_health_check_skip_preflight(self):
        report = run_health_check(
            config=PilotConfig(run_id="hc_test"),
            base_dir=ROOT,
            run_preflight=False,
        )
        self.assertIn(report["health_check"], ("PASS", "FAIL"))
        self.assertIn("checks", report)

    def test_create_mt5_executor_factory(self):
        executor = create_mt5_executor({"BASE_DIR": str(ROOT)})
        self.assertTrue(hasattr(executor, "execute"))


class TestPhase12Regime(unittest.TestCase):
    def test_classify_pilot_regime(self):
        import numpy as np
        import pandas as pd

        idx = pd.date_range("2024-01-01", periods=120, freq="5min", tz="UTC")
        closes = 2300.0 + np.cumsum(np.random.default_rng(1).normal(0, 0.2, 120))
        df = pd.DataFrame(
            {"open": closes, "high": closes + 0.5, "low": closes - 0.5, "close": closes, "volume": 100},
            index=idx,
        )
        regime = classify_pilot_regime(df, 100)
        self.assertIn(regime, ("LOW_VOLATILITY", "RANGE", "TREND", "HIGH_VOLATILITY"))


if __name__ == "__main__":
    unittest.main()
