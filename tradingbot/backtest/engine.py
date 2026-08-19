"""
موتور بک‌تست — همان TradingKernel را کندل‌به‌کندل روی داده‌ی تاریخی اجرا می‌کند.

ترتیب هر کندل (برای جلوگیری از look-ahead):
  1) چک خروج SL/TP پوزیشن‌های قبلی روی range کندل جدید
  2) mark-to-market + مدیریت پوزیشن هسته‌محور (trailing/partial/emergency)
  3) ورود جدید: اجرای pipeline هسته (Data→Indicators→Signals→Risk→Execution)
  4) ثبت نقطه‌ی equity
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.config.price_action import get_price_action_config
from tradingbot.config.pa_symbol_tf_presets import normalize_timeframe
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.ml.integration.factory import build_strategy_registry
from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter
from tradingbot.backtest.broker import SimulatedBroker
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.data_source import BacktestMarketData
from tradingbot.backtest.indicators import PassthroughIndicatorEngine
from tradingbot.backtest.metrics import compute_metrics, format_report
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.position_manager import BacktestPositionManager
from tradingbot.backtest.htf_provider import BacktestHtfBiasProvider
from tradingbot.backtest.risk import BacktestRiskGate
from tradingbot.config.settings import KernelSettings
from tradingbot.domain.models import MarketKey
from tradingbot.kernel.trading_kernel import TradingKernel

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(
        self,
        config: BacktestConfig,
        legacy_config: dict | None = None,
        *,
        quiet: bool = True,
        strategies=None,
    ) -> None:
        self._cfg = config
        self._quiet = quiet
        self._legacy_config = legacy_config if legacy_config is not None else load_legacy_config()

        if config.min_confidence is not None:
            self._legacy_config = dict(self._legacy_config)
            self._legacy_config["MIN_CONFIDENCE"] = config.min_confidence

        sc = self._legacy_config.get("PRICE_ACTION") or {}
        if sc:
            config.max_daily_loss_pct = float(
                sc.get("MAX_DAILY_LOSS_PCT", config.max_daily_loss_pct)
            )
            config.max_trades_per_day = int(
                sc.get("MAX_TRADES_PER_DAY", config.max_trades_per_day)
            )
            config.cooldown_bars = int(sc.get("COOLDOWN_BARS", config.cooldown_bars))
            config.max_consecutive_losses = int(
                sc.get("MAX_CONSECUTIVE_LOSSES", config.max_consecutive_losses)
            )
            config.cooldown_after_loss_bars = int(
                sc.get("COOLDOWN_AFTER_LOSS_BARS", config.cooldown_after_loss_bars)
            )
            config.min_balance_pct = float(
                sc.get("MIN_BALANCE_PCT", config.min_balance_pct)
            )
            config.spread_pips = float(sc.get("BASE_SPREAD_PIPS", config.spread_pips))
            config.slippage_pips = float(sc.get("BASE_SLIPPAGE_PIPS", config.slippage_pips))
            config.variable_spread = bool(sc.get("VARIABLE_SPREAD", config.variable_spread))
            config.max_spread_pips = float(sc.get("MAX_SPREAD_PIPS", config.max_spread_pips))
            config.use_news_filter = bool(sc.get("USE_NEWS_FILTER", config.use_news_filter))
            config.news_blackout_minutes = int(
                sc.get("NEWS_BLACKOUT_MINUTES", config.news_blackout_minutes)
            )
            config.friday_close_enabled = bool(
                sc.get("FRIDAY_CLOSE_ENABLED", config.friday_close_enabled)
            )
            config.friday_close_hour = int(
                sc.get("FRIDAY_CLOSE_HOUR", config.friday_close_hour)
            )
            config.friday_close_minute = int(
                sc.get("FRIDAY_CLOSE_MINUTE", config.friday_close_minute)
            )
            config.friday_no_entry_after_hour = int(
                sc.get("FRIDAY_NO_ENTRY_AFTER_HOUR", config.friday_no_entry_after_hour)
            )
            config.trailing_atr_mult = float(
                sc.get("TRAILING_ATR_MULT", config.trailing_atr_mult)
            )
            config.signal_window = int(
                sc.get("SIGNAL_WINDOW_BARS", config.signal_window)
            )
            config.max_open_positions_total = int(
                sc.get(
                    "MAX_OPEN_POSITIONS_TOTAL",
                    self._legacy_config.get(
                        "MAX_OPEN_POSITIONS_TOTAL", config.max_open_positions_total
                    ),
                )
            )
            config.max_positions_per_symbol = int(
                sc.get(
                    "MAX_OPEN_POSITIONS_PER_SYMBOL",
                    config.max_positions_per_symbol,
                )
            )
            config.require_htf_alignment_m5 = bool(
                sc.get("REQUIRE_HTF_ALIGNMENT_M5", config.require_htf_alignment_m5)
            )
            config.require_htf_alignment_m15 = bool(
                sc.get("REQUIRE_HTF_ALIGNMENT_M15", config.require_htf_alignment_m15)
            )
            config.require_htf_alignment_h4 = bool(
                sc.get("REQUIRE_HTF_ALIGNMENT_H4", config.require_htf_alignment_h4)
            )
            if "ENABLE_PARTIAL_TP" in sc:
                config.enable_partial_tp = bool(sc.get("ENABLE_PARTIAL_TP"))
            config.enable_zscore_exit = False

        sym = config.symbols[0] if config.symbols else "XAUUSD"
        entry_tf = normalize_timeframe(config.timeframe)
        pa_tf = get_price_action_config(sym, entry_tf)
        if "ENABLE_PARTIAL_TP" in pa_tf:
            config.enable_partial_tp = bool(pa_tf.get("ENABLE_PARTIAL_TP"))
        if "MAX_OPEN_POSITIONS_TOTAL" in pa_tf:
            config.max_open_positions_total = int(pa_tf["MAX_OPEN_POSITIONS_TOTAL"])
        if "MAX_OPEN_POSITIONS_PER_SYMBOL" in pa_tf:
            config.max_positions_per_symbol = int(pa_tf["MAX_OPEN_POSITIONS_PER_SYMBOL"])
        _htf_by_tf = {
            "M5": ("REQUIRE_HTF_ALIGNMENT_M5", "require_htf_alignment_m5"),
            "M15": ("REQUIRE_HTF_ALIGNMENT_M15", "require_htf_alignment_m15"),
            "H4": ("REQUIRE_HTF_ALIGNMENT_H4", "require_htf_alignment_h4"),
        }
        htf_key, htf_attr = _htf_by_tf.get(entry_tf, (None, None))
        if htf_key and htf_key in pa_tf:
            setattr(config, htf_attr, bool(pa_tf[htf_key]))

        self._data = BacktestMarketData(config, self._legacy_config)
        self._htf = BacktestHtfBiasProvider(
            config,
            self._legacy_config,
            symbol=sym,
            entry_timeframe=config.timeframe,
        )
        self._broker = SimulatedBroker(config, self._data)
        self._risk = BacktestRiskGate(config)
        self._position_manager = BacktestPositionManager(config, self._broker, self._data)
        if strategies is not None:
            self._strategies = strategies
        else:
            base_dir = self._legacy_config.get("BASE_DIR")
            self._strategies = build_strategy_registry(
                self._legacy_config, base_dir=base_dir,
            )


        settings = KernelSettings(
            symbols=list(config.symbols),
            timeframes=[config.timeframe],
            initial_balance=config.initial_balance,
            extra=self._legacy_config,
        )
        self._kernel = TradingKernel(
            settings=settings,
            market_data=self._data,
            indicators=PassthroughIndicatorEngine(),
            strategies=self._strategies,
            risk=self._risk,
            executor=self._broker,
            position_manager=self._position_manager,
        )

    @property
    def kernel(self) -> TradingKernel:
        return self._kernel

    @property
    def data_source(self) -> BacktestMarketData:
        return self._data

    async def run(self) -> BacktestResult:
        if self._data.length > 0:
            # داده از قبل تزریق شده (حالت تست)
            length = self._data.length
        else:
            # اتصال MT5 برای دریافت داده در صورت نبود کش (best-effort)
            try:
                md = Mt5MarketDataAdapter(self._legacy_config)
                await md.ensure_connected()
            except Exception as e:
                logger.debug("MT5 connect (for fetch) skipped: %s", e)
            length = self._data.load()
        if self._htf.needs_htf():
            self._htf.load()
        if length <= self._cfg.warmup + 1:
            raise RuntimeError(
                f"Not enough data ({length} bars) for warmup={self._cfg.warmup}"
            )

        markets = [MarketKey(symbol=s, timeframe=self._cfg.timeframe) for s in self._cfg.symbols]

        logger.info(
            "Backtest run: %s %s | bars=%d warmup=%d",
            self._cfg.symbols, self._cfg.timeframe, length, self._cfg.warmup,
        )

        equity_curve = []
        real_stdout = sys.stdout
        total = length - self._cfg.warmup
        with self._silence():
            for step, cursor in enumerate(range(self._cfg.warmup, length)):
                self._data.set_cursor(cursor)

                closed_before = len(self._broker.closed_trades)

                # 1) خروج پوزیشن‌های قبلی روی کندل جدید
                for symbol in self._cfg.symbols:
                    bar = self._data.current_bar(symbol)
                    if bar is not None:
                        self._broker.check_exits(symbol, bar)

                # 2) مدیریت پوزیشن هسته‌محور
                self._broker.mark_equity()
                self._position_manager.manage_all()

                for t in self._broker.closed_trades[closed_before:]:
                    self._risk.on_trade_closed(t.pnl, cursor)

                # 3) ورود جدید از مسیر هسته
                portfolio = self._broker.snapshot()
                if self._htf.needs_htf():
                    portfolio["htf_bias"] = self._htf.bias_at(self._data.current_time())
                for market in markets:
                    await self._kernel.run_market_cycle(market, portfolio)

                # 4) ثبت equity
                self._broker.mark_equity()
                equity_curve.append(
                    {
                        "time": str(self._data.current_time()),
                        "balance": self._broker.balance,
                        "equity": self._broker.equity,
                    }
                )

                if (
                    not self._quiet
                    and total >= 10
                    and step % max(1, total // 10) == 0
                ):
                    pct = step / total * 100
                    real_stdout.write(
                        f"  progress {pct:4.0f}% | bar {step}/{total} | "
                        f"equity {self._broker.equity:.2f} | trades {len(self._broker.closed_trades)}\n"
                    )
                    real_stdout.flush()

            # بستن همه‌ی پوزیشن‌های باز در پایان
            self._data.set_cursor(length - 1)
            self._broker.close_all("end")
            self._broker.mark_equity()

        result = BacktestResult(
            config=self._cfg,
            initial_balance=self._cfg.initial_balance,
            final_balance=self._broker.balance,
            trades=self._broker.closed_trades,
            equity_curve=equity_curve,
        )
        result.metrics = compute_metrics(result, self._cfg.timeframe)
        return result

    @contextmanager
    def _silence(self):
        """سرکوب print و لاگ‌های پرحجم legacy حین حلقه‌ی بک‌تست."""
        if not self._quiet:
            yield
            return
        old_stdout = sys.stdout
        noisy = ["", "TradingBot", "tradingbot", "core", "strategy_manager"]
        old_levels = {name: logging.getLogger(name).level for name in noisy}
        try:
            sys.stdout = open(os.devnull, "w")
            for name in noisy:
                logging.getLogger(name).setLevel(logging.ERROR)
            yield
        finally:
            if sys.stdout is not old_stdout:
                try:
                    sys.stdout.close()
                except Exception:
                    pass
                sys.stdout = old_stdout
            for name, lvl in old_levels.items():
                logging.getLogger(name).setLevel(lvl)

def report(result: BacktestResult) -> str:
    return format_report(result, result.metrics, result.config.timeframe)
