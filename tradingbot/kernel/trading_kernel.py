"""
TradingKernel — هسته مرکزی

تمام پردازش‌های پراکنده در پروژه قدیم از این کلاس عبور می‌کنند:
  SystemManager.run → DataPipeline → indicators → LiveTradingBot.generate_signal
  → risk → order

در نسخه جدید: run_global_cycle + run_market_cycle با pipeline ثابت.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from tradingbot.config.settings import KernelSettings
from tradingbot.domain.enums import KernelState, SignalDirection
from tradingbot.domain.models import CycleContext, MarketKey
from tradingbot.pipeline.base import PipelineStage
from tradingbot.pipeline.data_stage import DataStage
from tradingbot.pipeline.execution_stage import ExecutionStage
from tradingbot.pipeline.indicator_stage import IndicatorStage
from tradingbot.pipeline.risk_stage import RiskStage
from tradingbot.pipeline.signal_filter_stage import SignalFilterStage
from tradingbot.pipeline.signal_stage import SignalStage
from tradingbot.ports.execution import IOrderExecutor
from tradingbot.ports.indicators import IIndicatorEngine
from tradingbot.ports.market_data import IMarketDataProvider
from tradingbot.ports.position_manager import IPositionManager
from tradingbot.ports.risk import IRiskGate
from tradingbot.ports.strategies import IStrategyRegistry
from tradingbot.services.notifier import Notifier
from tradingbot.services.trade_journal import TradeJournal

logger = logging.getLogger(__name__)


class TradingKernel:
    """
    هسته مرکزی — تنها نقطه orchestration برای چرخه معاملاتی.

    مسئولیت‌ها (مطابق استاندارد Clean/Hexagonal):
      - چرخه زندگی (start/stop/emergency)
      - فراخوانی pipeline برای هر market
      - به‌روزرسانی سراسری داده قبل از botها
      - snapshot پورتفولیو برای risk stage
      - مدیریت کامل position (trailing/partial/emergency) از طریق position_manager

    غیرمسئولیت: منطق استراتژی، فرمول اندیکاتور، جزئیات MT5.
    """

    def __init__(
        self,
        settings: KernelSettings,
        market_data: IMarketDataProvider,
        indicators: IIndicatorEngine,
        strategies: IStrategyRegistry,
        risk: IRiskGate,
        executor: IOrderExecutor,
        position_manager: IPositionManager | None = None,
        extra_stages: Sequence[PipelineStage] | None = None,
    ) -> None:
        self.settings = settings
        self.state = KernelState.STOPPED
        self._market_data = market_data
        self._strategies = strategies
        self._risk = risk
        self._executor = executor
        self._position_manager = position_manager
        self._cycle_count = 0

        extra = getattr(settings, "extra", None) or {}
        base_dir = extra.get("BASE_DIR", ".")
        self._journal = TradeJournal(base_dir)
        self._notifier = Notifier(base_dir)
        pa = extra.get("PRICE_ACTION", {})
        min_bars = int(pa.get("MIN_BARS", 80))
        fetch_bars = int(pa.get("FETCH_BARS", pa.get("SIGNAL_WINDOW_BARS", 300)))
        self._health_max_tick_age = float(extra.get("HEALTH_MAX_TICK_AGE_SEC", 120.0))

        self._restore_emergency_stop_if_persisted()

        self._pipeline: list[PipelineStage] = [
            DataStage(market_data, min_bars=min_bars, fetch_bars=fetch_bars),
            IndicatorStage(indicators),
            SignalStage(strategies),
            SignalFilterStage(config=extra),
            RiskStage(risk),
            ExecutionStage(executor),
        ]
        if extra_stages:
            self._pipeline.extend(extra_stages)

    @property
    def pipeline_stages(self) -> list[str]:
        return [s.name.value for s in self._pipeline]

    @property
    def market_data(self) -> IMarketDataProvider:
        return self._market_data

    @property
    def executor(self) -> IOrderExecutor:
        return self._executor

    @property
    def position_manager(self) -> IPositionManager | None:
        return self._position_manager

    def markets(self) -> list[MarketKey]:
        return [
            MarketKey(symbol=s, timeframe=tf)
            for s in self.settings.symbols
            for tf in self.settings.timeframes
        ]

    async def run_global_cycle(self) -> dict[str, CycleContext]:
        """
        یک چرخه کامل سیستم — معادل بخش اصلی SystemManager.run loop:
          1) update_data همه symbolها
          2) run_market_cycle برای هر bot
          3) manage positions (trailing/partial/emergency) از هسته
        """
        if self.state == KernelState.EMERGENCY_STOP:
            logger.warning("Kernel in EMERGENCY_STOP — skipping cycle")
            return {}

        self._cycle_count += 1

        if hasattr(self._market_data, "ensure_connected"):
            connected = await self._market_data.ensure_connected()
            if not connected:
                logger.warning("Skipping cycle — MT5 not connected")
                self._journal.log_cycle("global", "mt5_disconnected", "ensure_connected failed")
                self._notifier.alert("warn", "MT5 not connected — cycle skipped")
                self._manage_positions()
                return {}

        from tradingbot.services.runtime_truth import entries_frozen, refresh_live_equity_from_mt5

        refresh_live_equity_from_mt5(log_freeze=True)
        equity_frozen = entries_frozen()

        if self.settings.symbols:
            from tradingbot.adapters.mt5_health import check_mt5_health
            from tradingbot.adapters.symbols import resolve_broker_symbol

            extra = getattr(self.settings, "extra", None) or {}
            broker_sym = resolve_broker_symbol(self.settings.symbols[0], extra)
            health = check_mt5_health(broker_sym, max_tick_age_sec=self._health_max_tick_age)
            if not health.connected:
                self._journal.log_cycle("global", "health_fail", health.reason)
                self._notifier.alert("warn", f"MT5 health: {health.reason}")
                self._manage_positions()
                return {}
            if health.reason != "ok":
                logger.warning("MT5 health warning: %s", health.reason)

        await self._market_data.update_all(
            self.settings.symbols, self.settings.timeframes
        )

        portfolio = self._portfolio_snapshot()
        portfolio["htf_bias_map"] = self._build_htf_bias_map()
        results: dict[str, CycleContext] = {}

        if not equity_frozen:
            for market in self.markets():
                ctx = await self.run_market_cycle(market, portfolio)
                results[str(market)] = ctx
                self._executor.manage_open_positions(str(market))
        else:
            self._journal.log_cycle("global", "equity_frozen", "new entries frozen")

        # مدیریت کامل پوزیشن‌ها (trailing/partial/emergency) — یک‌بار در هر چرخه سراسری
        self._manage_positions()

        return results

    def _manage_positions(self) -> None:
        if self._position_manager is None:
            return
        try:
            self._position_manager.manage_all()
        except Exception as e:
            logger.error("Position management failed: %s", e)

    async def run_market_cycle(
        self, market: MarketKey, portfolio_snapshot: dict | None = None
    ) -> CycleContext:
        """اجرای pipeline برای یک symbol:timeframe — معادل LiveTradingBot.run_live_cycle."""
        ctx = CycleContext(market=market)
        portfolio = portfolio_snapshot or self._portfolio_snapshot()

        for stage in self._pipeline:
            try:
                ok = await stage.run(ctx, portfolio)
                if not ok:
                    logger.debug(
                        "Pipeline stopped at %s for %s", stage.name.value, market
                    )
                    break
            except Exception as e:
                ctx.add_error(f"{stage.name.value}: {e}")
                logger.exception("Stage %s failed for %s", stage.name.value, market)
                break

        if ctx.signal and ctx.signal.direction != SignalDirection.HOLD:
            logger.info(
                "Cycle %s | %s | signal=%s conf=%.2f exec=%s",
                self._cycle_count,
                market,
                ctx.signal.direction.name,
                ctx.signal.confidence,
                ctx.execution.success if ctx.execution else None,
            )

        state = "executed" if ctx.execution and ctx.execution.success else "idle"
        if ctx.errors:
            state = "blocked"
        detail = "; ".join(ctx.errors) if ctx.errors else (
            f"signal={ctx.signal.direction.name}" if ctx.signal else "no_signal"
        )
        self._journal.log_cycle(str(market), state, detail)

        if self._cycle_count % 6 == 0:
            logger.info(
                "Kernel heartbeat | cycles=%s state=%s",
                self._cycle_count,
                self.state.name,
            )

        return ctx

    async def run_forever(self) -> None:
        """حلقه async — معادل asyncio.run(system_manager.run())."""
        if self.state == KernelState.EMERGENCY_STOP:
            logger.critical("Kernel refused to start — EMERGENCY_STOP already active")
            return
        self.state = KernelState.RUNNING
        interval = self.settings.cycle_interval_seconds
        logger.info("TradingKernel started — interval=%ss", interval)
        try:
            while self.state == KernelState.RUNNING:
                await self.run_global_cycle()
                await asyncio.sleep(interval)
        finally:
            if self.state == KernelState.RUNNING:
                self.state = KernelState.STOPPED
            else:
                logger.warning("TradingKernel loop ended — state=%s", self.state.name)

    def stop(self) -> None:
        self.state = KernelState.STOPPED

    def _restore_emergency_stop_if_persisted(self) -> None:
        from tradingbot.services.emergency_stop_state import read_emergency_stop

        snap = read_emergency_stop()
        if snap:
            self.state = KernelState.EMERGENCY_STOP
            logger.critical(
                "Restored EMERGENCY_STOP from disk | reason=%s | activated=%s",
                snap.get("reason"),
                snap.get("activated_utc"),
            )

    def emergency_stop(self, reason: str = "manual") -> None:
        from tradingbot.services.emergency_stop_state import activate_emergency_stop

        activate_emergency_stop(reason, source="trading_kernel")
        self.state = KernelState.EMERGENCY_STOP
        logger.critical("EMERGENCY_STOP activated: %s", reason)

    def _portfolio_snapshot(self) -> dict:
        if hasattr(self._risk, "portfolio_snapshot"):
            return self._risk.portfolio_snapshot()
        return {
            "balance": self.settings.initial_balance,
            "equity": self.settings.initial_balance,
            "open_positions": [],
            "correlation_data": {},
        }

    def _build_htf_bias_map(self) -> dict[str, int]:
        from tradingbot.config.price_action import get_price_action_config
        from tradingbot.domain.htf_bias import compute_htf_bias

        from tradingbot.domain.htf_bias import htf_timeframe_for

        out: dict[str, int] = {}
        timeframes = self.settings.timeframes or ["M15"]
        for sym in self.settings.symbols:
            for entry_tf in timeframes:
                htf_tf = htf_timeframe_for(entry_tf)
                mk = MarketKey(sym, htf_tf)
                try:
                    df = self._market_data.get_ohlcv(mk, bars=300)
                except Exception:
                    df = None
                if df is None or df.empty:
                    bias = 0
                else:
                    from tradingbot.domain.ohlcv import exclude_forming_bar

                    closed = exclude_forming_bar(df, min_rows=30)
                    use_df = closed if closed is not None and not closed.empty else df
                    cfg = get_price_action_config(sym, htf_tf)
                    bias = compute_htf_bias(use_df, cfg)
                out[f"{sym}:{entry_tf}"] = bias
                if sym not in out:
                    out[sym] = bias
        return out
