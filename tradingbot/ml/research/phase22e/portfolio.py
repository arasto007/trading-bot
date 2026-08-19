"""Phase 22E — shared-balance multi-timeframe portfolio backtest (research only)."""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.backtest.broker import SimulatedBroker
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.data_source import BacktestMarketData
from tradingbot.backtest.htf_provider import BacktestHtfBiasProvider
from tradingbot.backtest.indicators import PassthroughIndicatorEngine
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.position_manager import BacktestPositionManager
from tradingbot.backtest.risk import BacktestRiskGate
from tradingbot.config.settings import KernelSettings
from tradingbot.domain.models import MarketKey
from tradingbot.kernel.trading_kernel import TradingKernel
from tradingbot.ml.integration.factory import build_strategy_registry
from tradingbot.ml.research.phase22c.hold_chain import reset_hold_chain
from tradingbot.ml.research.phase22e.config import (
    BALANCE,
    SYMBOL,
    TIMEFRAMES,
    ValidationWindow,
    configure_production_env,
    data_window_days,
)
from tradingbot.ml.research.phase22e.metrics import compute_extended_metrics
from scripts.backtest_custom_range import entry_in_tehran_range

TEHRAN = ZoneInfo("Asia/Tehran")
logger = logging.getLogger(__name__)


@dataclass
class _TfRuntime:
    timeframe: str
    data: BacktestMarketData
    htf: BacktestHtfBiasProvider
    kernel: TradingKernel
    length: int
    warmup: int


@contextmanager
def _silence():
    old_stdout = sys.stdout
    noisy = ["", "TradingBot", "tradingbot", "core", "strategy_manager"]
    old_levels = {name: logging.getLogger(name).level for name in noisy}
    try:
        sys.stdout = open(os.devnull, "w")
        for name in noisy:
            logging.getLogger(name).setLevel(logging.ERROR)
        yield
    finally:
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.stdout = old_stdout
        for name, lvl in old_levels.items():
            logging.getLogger(name).setLevel(lvl)


async def run_portfolio_backtest(
    window: ValidationWindow,
    *,
    balance: float = BALANCE,
    spread_pips: float | None = None,
    slippage_pips: float | None = None,
) -> dict[str, Any]:
    """
    Simultaneous M5/M15/H4 with shared balance, RiskGate, and drawdown.
    Research-only — does not modify BacktestEngine.
    """
    configure_production_env()
    reset_hold_chain()

    from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter

    legacy = load_legacy_config()
    base_dir = legacy.get("BASE_DIR")
    strategies = build_strategy_registry(legacy, base_dir=base_dir)

    shared_cfg = BacktestConfig(
        symbols=[SYMBOL],
        timeframe="M5",
        initial_balance=balance,
        use_cache=False,
    )
    if spread_pips is not None:
        shared_cfg.spread_pips = spread_pips
    if slippage_pips is not None:
        shared_cfg.slippage_pips = slippage_pips

    runtimes: list[_TfRuntime] = []
    now_tehran = datetime.now(TEHRAN)

    for tf in TIMEFRAMES:
        days, offset = data_window_days(tf, window.start, window.end, now_tehran)
        bc = BacktestConfig(
            symbols=[SYMBOL],
            timeframe=tf,
            days=days,
            start_offset_days=offset,
            initial_balance=balance,
            use_cache=False,
            spread_pips=shared_cfg.spread_pips,
            slippage_pips=shared_cfg.slippage_pips,
        )
        data = BacktestMarketData(bc, legacy)
        htf = BacktestHtfBiasProvider(bc, legacy, symbol=SYMBOL, entry_timeframe=tf)
        runtimes.append(_TfRuntime(tf, data, htf, None, 0, bc.warmup))  # type: ignore[arg-type]

    try:
        md = Mt5MarketDataAdapter(legacy)
        await md.ensure_connected()
    except Exception as exc:
        logger.debug("MT5 connect skipped: %s", exc)

    for rt in runtimes:
        rt.length = rt.data.load()
        if rt.htf.needs_htf():
            rt.htf.load()
        if rt.length <= rt.warmup + 1:
            raise RuntimeError(f"Not enough data for {rt.timeframe} ({rt.length} bars)")

    primary = runtimes[0].data
    broker = SimulatedBroker(shared_cfg, primary)
    risk = BacktestRiskGate(shared_cfg)
    pos_mgr = BacktestPositionManager(shared_cfg, broker, primary)

    for rt in runtimes:
        rt.kernel = TradingKernel(
            settings=KernelSettings(
                symbols=[SYMBOL],
                timeframes=[rt.timeframe],
                initial_balance=shared_cfg.initial_balance,
                extra=legacy,
            ),
            market_data=rt.data,
            indicators=PassthroughIndicatorEngine(),
            strategies=strategies,
            risk=risk,
            executor=broker,
            position_manager=pos_mgr,
        )

    position_tf: dict[int, str] = {}
    active_tf: list[str] = ["M5"]
    orig_execute = broker.execute

    def _tracked_execute(signal, lot):
        result = orig_execute(signal, lot)
        if result.success and broker.open_positions:
            position_tf[broker.open_positions[-1].ticket] = active_tf[0]
        return result

    broker.execute = _tracked_execute  # type: ignore[method-assign]

    events: list[tuple[datetime, str, int]] = []
    for rt in runtimes:
        for cursor in range(rt.warmup, rt.length):
            rt.data.set_cursor(cursor)
            ts = rt.data.current_time()
            if ts is not None and entry_in_tehran_range(ts, window.start, window.end):
                events.append((ts, rt.timeframe, cursor))
    events.sort(key=lambda x: x[0])

    t0 = time.perf_counter()
    equity_curve: list[dict] = []

    with _silence():
        for ts, tf, cursor in events:
            rt = next(r for r in runtimes if r.timeframe == tf)
            rt.data.set_cursor(cursor)
            active_tf[0] = tf
            broker._data = rt.data  # noqa: SLF001
            pos_mgr._data = rt.data  # noqa: SLF001

            closed_before = len(broker.closed_trades)
            bar = rt.data.current_bar(SYMBOL)
            if bar is not None:
                for pos in list(broker.open_positions):
                    if position_tf.get(pos.ticket) == tf:
                        broker.check_exits(SYMBOL, bar)

            broker.mark_equity()
            pos_mgr.manage_all()
            for t in broker.closed_trades[closed_before:]:
                risk.on_trade_closed(t.pnl, cursor)

            portfolio = broker.snapshot()
            portfolio["cursor"] = cursor
            if rt.htf.needs_htf():
                portfolio["htf_bias"] = rt.htf.bias_at(ts)
            frame = rt.data.frame(SYMBOL)
            if frame is not None:
                portfolio["ohlcv"] = frame

            market = MarketKey(symbol=SYMBOL, timeframe=tf)
            await rt.kernel.run_market_cycle(market, portfolio)

            broker.mark_equity()
            equity_curve.append(
                {"time": str(ts), "timeframe": tf, "balance": broker.balance, "equity": broker.equity}
            )

        last_rt = runtimes[0]
        last_rt.data.set_cursor(last_rt.length - 1)
        broker._data = last_rt.data
        broker.close_all("end")
        broker.mark_equity()

    elapsed = time.perf_counter() - t0
    filtered = [t for t in broker.closed_trades if entry_in_tehran_range(t.entry_time, window.start, window.end)]
    result = BacktestResult(
        config=shared_cfg,
        initial_balance=balance,
        final_balance=broker.balance,
        trades=filtered,
        equity_curve=equity_curve,
    )
    metrics = compute_extended_metrics(result, "M5")

    return {
        "phase": "22E",
        "mode": "shared_portfolio",
        "window": window.to_dict(),
        "timeframes": list(TIMEFRAMES),
        "initial_balance": balance,
        "final_balance": round(broker.balance, 2),
        "elapsed_sec": round(elapsed, 1),
        "events_processed": len(events),
        "metrics": metrics,
        "trades": len(filtered),
        "pipeline_note": "Shared SimulatedBroker + BacktestRiskGate across M5/M15/H4 chronological events",
    }
