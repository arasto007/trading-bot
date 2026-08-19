"""
LiveRunner — حلقه دائمی معاملات + سرویس‌های پس‌زمینه + خاموشی امن.

جایگزین run_system_manager.py قدیم:
  - اتصال MT5
  - شروع PositionRecoveryService (PositionProtector به‌صورت پیش‌فرض خاموش)
  - kernel.run_forever() — مدیریت پوزیشن از مسیر هسته انجام می‌شود
  - توقف امن با Ctrl+C
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
from tradingbot.adapters.background_services import BackgroundServices
from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.adapters.risk_gate import create_risk_gate
from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter
from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter
from tradingbot.adapters.mt5_position_manager import Mt5PositionManager
from tradingbot.config.legacy_settings import kernel_settings_from_legacy
from tradingbot.config.settings import KernelSettings
from tradingbot.domain.enums import KernelState
from tradingbot.kernel.trading_kernel import TradingKernel
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.ml.integration.factory import build_strategy_registry
from tradingbot.services.emergency_stop_state import read_emergency_stop
from tradingbot.services.execution_mode import mode_label
from tradingbot.services.kill_switch import KillSwitchService
from tradingbot.services.live_ops_service import LiveOpsService
from tradingbot.services.manual_stop import set_manual_stop
from tradingbot.services.notifier import Notifier
from tradingbot.services.startup_validator import (
    StartupValidationError,
    log_startup_report,
    validate_startup,
    write_startup_report,
)

logger = logging.getLogger(__name__)

CANONICAL_SYMBOL = PRIMARY_SYMBOL


class _ReliabilityKernel(TradingKernel):
    """TradingKernel with Phase 38A stale-bar entry freeze before each cycle."""

    def __init__(self, *args, legacy_config: dict | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._legacy_config = legacy_config or {}

    async def run_global_cycle(self) -> dict:
        from tradingbot.services import runtime_truth as rt

        self._refresh_market_data_stale_state()
        _orig_entries_frozen = rt.entries_frozen

        def _entries_blocked() -> bool:
            return _orig_entries_frozen() or rt.market_data_stale()

        rt.entries_frozen = _entries_blocked
        try:
            return await super().run_global_cycle()
        finally:
            rt.entries_frozen = _orig_entries_frozen

    def _refresh_market_data_stale_state(self) -> None:
        import MetaTrader5 as mt5

        from tradingbot.adapters.symbols import resolve_broker_symbol
        from tradingbot.services.runtime_truth import (
            mt5_rates_to_ohlcv_dataframe,
            update_market_data_state,
        )

        broker = resolve_broker_symbol(CANONICAL_SYMBOL, self._legacy_config)
        try:
            rates = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_M5, 0, 1)
            df = mt5_rates_to_ohlcv_dataframe(rates, timeframe_minutes=5)
            if df.empty:
                update_market_data_state(None)
                return
            last_ts = df.index[-1].to_pydatetime()
            update_market_data_state(last_ts)
        except Exception:
            update_market_data_state(None)


class LiveRunner:
    """مالک چرخه زندگی کامل ربات live."""

    def __init__(
        self,
        settings: KernelSettings | None = None,
        *,
        dry_run: bool = True,
        paper: bool = False,
        enable_protector: bool = False,
        enable_recovery: bool = False,
    ) -> None:
        self.settings = settings or kernel_settings_from_legacy()
        self.legacy_config = self.settings.extra or {}
        self.dry_run = dry_run
        self.paper = paper
        self.enable_protector = enable_protector
        self.enable_recovery = enable_recovery

        os.environ.pop("TRADINGBOT_DRY_RUN", None)
        os.environ.pop("TRADINGBOT_PAPER", None)
        if paper:
            os.environ["TRADINGBOT_PAPER"] = "1"
        elif dry_run:
            os.environ["TRADINGBOT_DRY_RUN"] = "1"
        if not dry_run and not paper:
            os.environ["TRADINGBOT_LIVE"] = "1"

        base_dir = self.legacy_config.get("BASE_DIR", ".")
        self._notifier = Notifier(base_dir)

        self.market_data = Mt5MarketDataAdapter(self.legacy_config)
        self.executor = Mt5ExecutionAdapter(self.legacy_config)
        self.risk_gate = create_risk_gate(self.legacy_config)

        # مدیریت پوزیشن از مسیر هسته (trailing/partial/emergency).
        self.position_manager = Mt5PositionManager(self.legacy_config)

        self.kernel = _ReliabilityKernel(
            settings=self.settings,
            market_data=self.market_data,
            indicators=TechnicalIndicatorEngine(self.legacy_config),
            strategies=build_strategy_registry(
                self.legacy_config,
                base_dir=base_dir,
            ),
            risk=self.risk_gate,
            executor=self.executor,
            position_manager=self.position_manager,
            legacy_config=self.legacy_config,
        )

        # PositionProtector قدیم به‌صورت پیش‌فرض خاموش است تا با مدیریت هسته
        # تداخل (مثل partial-close دوباره) ایجاد نشود.
        self.services = BackgroundServices(
            self.legacy_config,
            enable_protector=enable_protector,
            enable_recovery=enable_recovery,
        )
        self.kill_switch = KillSwitchService(self.kernel, self.legacy_config)
        self.live_ops = LiveOpsService(self.legacy_config)

    async def _run(self) -> None:
        try:
            skip_mt5 = os.environ.get("TRADINGBOT_SKIP_MT5_STARTUP", "").lower() in ("1", "true", "yes")
            try:
                report = validate_startup(
                    settings=self.settings,
                    legacy_config=self.legacy_config,
                    dry_run=self.dry_run,
                    paper=self.paper,
                    enable_protector=self.enable_protector,
                    enable_recovery=self.enable_recovery,
                    skip_mt5=skip_mt5,
                )
            except StartupValidationError as exc:
                logger.critical("STARTUP FAILED | code=%s | reason=%s", exc.code, exc.reason)
                self._notifier.alert("critical", f"Startup refused: {exc.code} — {exc.reason}")
                sys.exit(1)

            base_dir = self.legacy_config.get("BASE_DIR", ".")
            write_startup_report(report, base_dir)
            log_startup_report(report)

            from tradingbot.services.runtime_truth import write_runtime_truth

            write_runtime_truth(legacy_config=self.legacy_config, print_console=True)

            connected = await self.market_data.ensure_connected()
            if not connected and not skip_mt5:
                logger.critical("MT5 not connected after startup validation — aborting")
                sys.exit(1)
            if not connected and skip_mt5:
                logger.warning("MT5 not connected (TRADINGBOT_SKIP_MT5_STARTUP=1)")
            elif not skip_mt5:
                from tradingbot.services.runtime_truth import lock_live_equity_at_startup

                ok, equity = lock_live_equity_at_startup()
                if not ok:
                    logger.error("Live startup refused — real MT5 equity required")
                    sys.exit(1)
                logger.info("Live equity locked at startup | equity=%.2f", equity)
                self.risk_gate._sync_mt5_account()
                self._calibrate_mt5_bar_timezone()
                await self._startup_position_reconciliation()

            self.services.start_all()
            self.kill_switch.start()
            if not self.dry_run and not self.paper:
                self.live_ops.start()
            logger.info(
                "LiveRunner started | mode=%s | symbols=%s | interval=%ss",
                mode_label(),
                self.settings.symbols,
                self.settings.cycle_interval_seconds,
            )
            self._notifier.alert(
                "info",
                f"LiveRunner started | mode={mode_label()} | symbols={self.settings.symbols}",
            )
            await self.kernel.run_forever()
            if self.kernel.state == KernelState.EMERGENCY_STOP or read_emergency_stop():
                snap = read_emergency_stop() or {}
                logger.critical(
                    "Exiting with code 2 (Kill Switch) | reason=%s",
                    snap.get("reason"),
                )
                sys.exit(2)
            if self.kernel.state != KernelState.RUNNING:
                logger.warning(
                    "Kernel loop ended unexpectedly | state=%s — exiting 0",
                    self.kernel.state.name,
                )
        finally:
            await self._shutdown()

    def _calibrate_mt5_bar_timezone(self) -> None:
        """Detect broker-server UTC offset once at startup (Phase 38C)."""
        import MetaTrader5 as mt5

        from tradingbot.adapters.symbols import resolve_broker_symbol
        from tradingbot.services.runtime_truth import (
            mt5_rates_to_ohlcv_dataframe,
            mt5_timezone_metadata,
        )

        broker = resolve_broker_symbol(CANONICAL_SYMBOL, self.legacy_config)
        try:
            rates = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_M5, 0, 3)
            mt5_rates_to_ohlcv_dataframe(rates, timeframe_minutes=5)
            meta = mt5_timezone_metadata()
            offset = int(meta.get("mt5_utc_offset_seconds") or 0)
            if offset:
                logger.info("MT5 bar timezone calibrated | offset_seconds=%d", offset)
        except Exception as exc:
            logger.warning("MT5 bar timezone calibration failed: %s", exc)

    async def _startup_position_reconciliation(self) -> None:
        """Reconcile open XAUUSD positions once after MT5 connect (Phase 38A)."""
        import MetaTrader5 as mt5

        from tradingbot.adapters.symbols import resolve_broker_symbol

        broker = resolve_broker_symbol(CANONICAL_SYMBOL, self.legacy_config)
        try:
            positions = mt5.positions_get(symbol=broker)
            count = len(positions) if positions else 0
            logger.info(
                "Startup reconciliation | open_positions=%d symbol=%s",
                count,
                broker,
            )
            if count > 0 and self.position_manager is not None:
                self.position_manager.manage_all()
        except Exception as exc:
            logger.error("Startup position reconciliation failed: %s", exc)

    async def _shutdown(self) -> None:
        logger.info("Shutting down LiveRunner...")
        self.kernel.stop()
        self.kill_switch.stop()
        self.live_ops.stop()
        self.services.stop_all()
        try:
            await self.market_data.shutdown()
        except Exception as e:
            logger.debug("MT5 shutdown error: %s", e)
        logger.info("LiveRunner stopped cleanly | kernel_state=%s", self.kernel.state.name)
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass

    def _heartbeat_loop(self, stop: threading.Event) -> None:
        """Publish live_heartbeat.json every 60s even if the kernel is blocked."""
        from tradingbot.services.live_loop_health import (
            HEARTBEAT_INTERVAL_SEC,
            publish_runner_heartbeat,
        )

        try:
            publish_runner_heartbeat(self)
        except Exception:
            logger.debug("initial heartbeat publish failed", exc_info=True)
        while not stop.wait(HEARTBEAT_INTERVAL_SEC):
            try:
                publish_runner_heartbeat(self)
            except Exception:
                logger.debug("heartbeat publish failed", exc_info=True)

    def run(self) -> None:
        stop = threading.Event()
        hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(stop,),
            name="live-heartbeat",
            daemon=True,
        )
        hb_thread.start()
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            logger.info("Interrupted by user (Ctrl+C)")
            set_manual_stop("ctrl_c")
            sys.exit(0)
        finally:
            stop.set()
            hb_thread.join(timeout=2)


def run_live_loop(
    *,
    dry_run: bool = True,
    paper: bool = False,
    enable_protector: bool = False,
    enable_recovery: bool = False,
) -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    from tradingbot.config.live import get_live_config

    live = get_live_config()
    if (
        live.get("ADAPTIVE_REGIME_ENABLED")
        or live.get("VOL_REGIME_ENABLED")
        or live.get("MULTI_ENGINE_ROUTER_ENABLED")
    ):
        enable_protector = False
        enable_recovery = False
    runner = LiveRunner(
        dry_run=dry_run,
        paper=paper,
        enable_protector=enable_protector,
        enable_recovery=enable_recovery,
    )
    runner.run()
