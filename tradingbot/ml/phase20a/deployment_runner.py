"""Phase 20A — live deployment runner (wraps TradingKernel live loop)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from tradingbot.adapters.background_services import BackgroundServices
from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter
from tradingbot.adapters.mt5_position_manager import Mt5PositionManager
from tradingbot.adapters.risk_gate import create_risk_gate
from tradingbot.config.legacy_settings import kernel_settings_from_legacy
from tradingbot.domain.enums import KernelState
from tradingbot.kernel.trading_kernel import TradingKernel
from tradingbot.ml.integration.live_preflight import run_live_preflight
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase20a.config import DeploymentConfig, apply_certified_env, is_live_execution_enabled
from tradingbot.ml.phase20a.execution_guard import build_phase20a_executor
from tradingbot.ml.phase20a.reporter import Phase20aReporter
from tradingbot.ml.phase20a.safety_monitor import Phase20aSafetyMonitor
from tradingbot.ml.phase20a.strategy_registry import build_phase20a_strategy_registry
from tradingbot.services.kill_switch import KillSwitchService
from tradingbot.services.manual_stop import set_manual_stop
from tradingbot.services.notifier import Notifier

logger = logging.getLogger(__name__)


class Phase20aDeploymentRunner:
    """Certified production live loop — does not modify TradingKernel internals."""

    def __init__(self, config: DeploymentConfig) -> None:
        self.config = config
        apply_certified_env(config)
        PipelineCache.reset()

        self.legacy_config = load_legacy_config()
        self.legacy_config["RISK_PER_TRADE"] = config.risk_pct
        self.legacy_config["MAX_OPEN_POSITIONS_TOTAL"] = config.max_open_positions
        self.legacy_config["MAX_OPEN_POSITIONS_PER_SYMBOL"] = config.max_open_positions
        self.legacy_config["MAX_TRADES_PER_DAY"] = config.max_trades_per_day
        self.legacy_config["PRICE_ACTION"] = {
            **self.legacy_config.get("PRICE_ACTION", {}),
            "MAX_DRAWDOWN_PCT": 0.10,
        }

        self.settings = kernel_settings_from_legacy()
        self.reporter = Phase20aReporter(base_dir=config.base_dir)
        self.safety = Phase20aSafetyMonitor(config)
        self._notifier = Notifier(self.legacy_config.get("BASE_DIR", "."))
        self._flush_thread: threading.Thread | None = None
        self._running = False

        self.market_data = Mt5MarketDataAdapter(self.legacy_config)
        self.executor = build_phase20a_executor(
            self.legacy_config,
            safety=self.safety,
            reporter=self.reporter,
        )
        self.risk_gate = create_risk_gate(self.legacy_config)
        self.position_manager = Mt5PositionManager(self.legacy_config)
        strategies = build_phase20a_strategy_registry(
            self.legacy_config,
            base_dir=config.base_dir,
            symbol=config.symbol,
            reporter=self.reporter,
            safety=self.safety,
        )

        self.kernel = TradingKernel(
            settings=self.settings,
            market_data=self.market_data,
            indicators=TechnicalIndicatorEngine(self.legacy_config),
            strategies=strategies,
            risk=self.risk_gate,
            executor=self.executor,
            position_manager=self.position_manager,
        )
        self.services = BackgroundServices(self.legacy_config, enable_protector=False, enable_recovery=True)
        self.kill_switch = KillSwitchService(self.kernel, self.legacy_config)

    def preflight(self) -> dict[str, Any]:
        if self.config.skip_preflight:
            return {"preflight_pass": True, "skipped": True}
        return run_live_preflight(
            self.config.symbol,
            self.config.timeframe,
            config=self.legacy_config,
            base_dir=self.config.base_dir,
        )

    def _flush_loop(self) -> None:
        while self._running:
            try:
                self._update_account_metrics()
                self.reporter.flush_all()
                if self.safety.should_stop:
                    logger.critical("Phase20A safety stop — halting kernel")
                    self.kernel.emergency_stop()
                    break
            except Exception as exc:  # noqa: BLE001
                logger.debug("flush error: %s", exc)
            time.sleep(30)

    def _update_account_metrics(self) -> None:
        try:
            import MetaTrader5 as mt5

            info = mt5.account_info()
            if info is None:
                return
            equity = float(info.equity)
            balance = float(info.balance)
            ts = datetime.now(timezone.utc).isoformat()
            self.reporter.log_equity({
                "timestamp": ts,
                "equity": equity,
                "balance": balance,
            })
            self.safety.record_equity(equity)
            peak = self.safety._state.peak_equity  # noqa: SLF001
            if peak > 0:
                dd = (peak - equity) / peak
                self.reporter.log_drawdown({
                    "timestamp": ts,
                    "drawdown_pct": round(dd * 100, 4),
                    "equity": equity,
                    "peak": peak,
                })
            self.reporter.log_health({
                "timestamp": ts,
                "safety": self.safety.summary(),
                "kernel_state": self.kernel.state.name,
                "live_enabled": is_live_execution_enabled(),
            })
        except Exception:
            pass

    async def _run_async(self) -> None:
        connected = await self.market_data.ensure_connected()
        if not connected:
            raise RuntimeError("MT5 connection failed")

        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

        self.services.start_all()
        self.kill_switch.start()
        logger.info(
            "Phase20A live deployment running | symbol=%s | risk=%.2f%% | live_orders=%s",
            self.config.symbol,
            self.config.risk_pct * 100,
            is_live_execution_enabled(),
        )
        self._notifier.alert(
            "info",
            f"Phase20A LIVE_DEPLOYMENT_STARTED | {self.config.symbol} | risk={self.config.risk_pct:.2%}",
        )

        await self.kernel.run_forever()

        if self.kernel.state == KernelState.EMERGENCY_STOP:
            logger.critical("Kernel emergency stop")

    async def _shutdown(self) -> None:
        self._running = False
        self.kernel.stop()
        self.kill_switch.stop()
        self.services.stop_all()
        try:
            await self.market_data.shutdown()
        except Exception:
            pass
        self.reporter.flush_all()

    def run(self) -> None:
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            set_manual_stop("ctrl_c")

    async def _run(self) -> None:
        try:
            await self._run_async()
        finally:
            await self._shutdown()
