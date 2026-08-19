"""Phase 24K — production blocker regression tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.ml_kernel_registry import MLKernelRegistry
from tradingbot.services.live_risk_tracker import LiveRiskTracker


class TestLiveRiskTrackerAUD002(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "live_risk_state.json"
        self.tracker = LiveRiskTracker(path=self._path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_entry_allowed_no_exception(self) -> None:
        ok, reason = self.tracker.check_entry_allowed(
            timeframe="M5",
            max_trades_per_day=0,
            cooldown_bars=0,
            equity=10_000.0,
            initial_balance=10_000.0,
            max_daily_loss_pct=0.04,
            config={"RISK_PER_TRADE": 0.005},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def _init_day(self) -> None:
        self.tracker.check_entry_allowed(
            timeframe="M5",
            max_trades_per_day=0,
            cooldown_bars=0,
            equity=10_000.0,
            initial_balance=10_000.0,
            max_daily_loss_pct=0.04,
            config={"RISK_PER_TRADE": 0.005},
        )

    def test_entry_denied_max_trades(self) -> None:
        self._init_day()
        self.tracker.record_entry("M5")
        self.tracker.record_entry("M5")
        ok, reason = self.tracker.check_entry_allowed(
            timeframe="M5",
            max_trades_per_day=2,
            cooldown_bars=0,
            equity=10_000.0,
            initial_balance=10_000.0,
            max_daily_loss_pct=0.04,
            config={"risk_per_trade": 0.01},
        )
        self.assertFalse(ok)
        self.assertIn("max trades", reason)

    def test_restart_loads_state(self) -> None:
        self._init_day()
        self.tracker.record_entry("M15")
        tracker2 = LiveRiskTracker(path=self._path)
        ok, _ = tracker2.check_entry_allowed(
            timeframe="M15",
            max_trades_per_day=1,
            cooldown_bars=0,
            equity=10_000.0,
            initial_balance=10_000.0,
            max_daily_loss_pct=0.04,
            config={"RISK_PER_TRADE": 0.005},
        )
        self.assertFalse(ok)


class TestPaperModeGuardAUD001(unittest.TestCase):
    def test_guarded_order_send_blocks_in_paper(self) -> None:
        from tradingbot.services.mt5_order_guard import guarded_order_send

        fake_mt5 = SimpleNamespace(
            TRADE_RETCODE_DONE=10009,
            order_send=mock.Mock(return_value=SimpleNamespace(retcode=999)),
        )
        with mock.patch.dict(os.environ, {"TRADINGBOT_PAPER": "1"}, clear=False):
            os.environ.pop("TRADINGBOT_DRY_RUN", None)
            result = guarded_order_send(
                fake_mt5,
                {"symbol": "XAUUSD", "volume": 0.01, "action": 1, "price": 2000.0},
                label="test",
            )
        fake_mt5.order_send.assert_not_called()
        self.assertEqual(result.retcode, 10009)

    def test_guarded_order_send_blocks_in_dry_run(self) -> None:
        from tradingbot.services.mt5_order_guard import guarded_order_send

        fake_mt5 = SimpleNamespace(
            TRADE_RETCODE_DONE=10009,
            order_send=mock.Mock(),
        )
        with mock.patch.dict(os.environ, {"TRADINGBOT_DRY_RUN": "1"}, clear=False):
            os.environ.pop("TRADINGBOT_PAPER", None)
            guarded_order_send(fake_mt5, {"symbol": "X", "volume": 0.01}, label="test")
        fake_mt5.order_send.assert_not_called()


class TestStartupDiagnosticsAUD003(unittest.TestCase):
    def test_unconfigured_when_env_absent(self) -> None:
        from tradingbot.ml.integration.factory import UnconfiguredEngineRegistry, build_strategy_registry
        from tradingbot.ml.integration.startup_diagnostics import resolve_engine_selection

        os.environ.pop("USE_ML_KERNEL", None)
        sel = resolve_engine_selection()
        self.assertEqual(sel.selected_engine, "UNCONFIGURED")
        reg = build_strategy_registry({})
        self.assertIsInstance(reg, UnconfiguredEngineRegistry)

    def test_explicit_legacy_when_false(self) -> None:
        from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
        from tradingbot.ml.integration.factory import build_strategy_registry
        from tradingbot.ml.integration.startup_diagnostics import resolve_engine_selection

        os.environ["USE_ML_KERNEL"] = "0"
        try:
            sel = resolve_engine_selection()
            self.assertEqual(sel.selected_engine, "LEGACY_PRICE_ACTION")
            reg = build_strategy_registry({})
            self.assertIsInstance(reg, LegacyStrategyRegistry)
        finally:
            os.environ.pop("USE_ML_KERNEL", None)


class TestEmergencyStopPersistence(unittest.TestCase):
    def setUp(self) -> None:
        from tradingbot.services import emergency_stop_state as ess

        self._orig = ess.STATE_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        ess.STATE_PATH = Path(self._tmpdir.name) / "emergency_stop.json"

    def tearDown(self) -> None:
        from tradingbot.services import emergency_stop_state as ess

        ess.STATE_PATH = self._orig
        self._tmpdir.cleanup()

    def test_persist_and_restore(self) -> None:
        from tradingbot.domain.enums import KernelState
        from tradingbot.services.emergency_stop_state import (
            activate_emergency_stop,
            clear_emergency_stop,
            is_emergency_stop_active,
        )

        activate_emergency_stop("test drawdown")
        self.assertTrue(is_emergency_stop_active())

        from tradingbot.config.settings import KernelSettings
        from tradingbot.kernel.trading_kernel import TradingKernel

        kernel = TradingKernel(
            settings=KernelSettings(symbols=["XAUUSD"], timeframes=["M5"]),
            market_data=mock.Mock(),
            indicators=mock.Mock(),
            strategies=mock.Mock(),
            risk=mock.Mock(),
            executor=mock.Mock(),
        )
        self.assertEqual(kernel.state, KernelState.EMERGENCY_STOP)
        clear_emergency_stop()
        self.assertFalse(is_emergency_stop_active())


class TestPositionOwnerDefault(unittest.TestCase):
    def test_live_runner_recovery_default_off(self) -> None:
        from tradingbot.application.live_runner import LiveRunner

        with mock.patch.object(LiveRunner, "__init__", lambda self, *a, **k: None):
            runner = LiveRunner.__new__(LiveRunner)
        sig = LiveRunner.__init__.__annotations__ if hasattr(LiveRunner.__init__, "__annotations__") else {}
        import inspect

        params = inspect.signature(LiveRunner.__init__).parameters
        self.assertEqual(params["enable_recovery"].default, False)


class TestFallbackAUD006(unittest.TestCase):
    def test_safe_hold_when_fallback_disabled(self) -> None:
        legacy = mock.Mock()
        adapter = mock.Mock()
        adapter.generate_signal.side_effect = KernelFallbackError("health_fail")
        reg = MLKernelRegistry({}, legacy=legacy, adapter=adapter)
        os.environ["USE_ML_KERNEL"] = "1"
        os.environ.pop("ALLOW_LEGACY_FALLBACK", None)
        try:
            out = reg.generate_signal(MarketKey("XAUUSD", "M5"), pd.DataFrame({"close": [1.0]}))
            self.assertIsNone(out)
            self.assertEqual(reg.last_source, "safe_hold")
            self.assertEqual(reg.hold_count, 1)
            legacy.generate_signal.assert_not_called()
        finally:
            os.environ.pop("USE_ML_KERNEL", None)


class TestTimeoutDiagnosticsAUD007(unittest.TestCase):
    def test_record_pipeline_timeout(self) -> None:
        from tradingbot.ml.integration.timeout_diagnostics import (
            clear_pipeline_timeout_log,
            last_pipeline_timeout,
            record_pipeline_timeout,
        )

        clear_pipeline_timeout_log()
        record_pipeline_timeout({"stage": "produce_unified_signal", "elapsed_ms": 600.0})
        snap = last_pipeline_timeout()
        self.assertIsNotNone(snap)
        self.assertEqual(snap["stage"], "produce_unified_signal")


class TestAutotradingAUD008(unittest.TestCase):
    def test_execute_checks_autotrading_before_live(self) -> None:
        from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter
        from tradingbot.domain.models import TradingSignal

        adapter = Mt5ExecutionAdapter({"BASE_DIR": "."})
        signal = TradingSignal(
            direction=SignalDirection.BUY,
            confidence=0.8,
            symbol="XAUUSD",
            timeframe="M5",
        )
        os.environ.pop("TRADINGBOT_DRY_RUN", None)
        os.environ.pop("TRADINGBOT_PAPER", None)
        with mock.patch(
            "tradingbot.adapters.mt5_execution.ensure_mt5_connected",
            return_value=True,
        ), mock.patch(
            "tradingbot.adapters.mt5_health.check_autotrading_ready",
            return_value=(False, "AutoTrading OFF"),
        ):
            result = adapter.execute(signal, 0.01)
        self.assertFalse(result.success)
        self.assertIn("AutoTrading", result.message)


if __name__ == "__main__":
    unittest.main()
