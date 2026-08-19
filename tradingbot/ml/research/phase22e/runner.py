"""Phase 22E — production-path single-timeframe backtest runner."""

from __future__ import annotations

import time
from typing import Any

from tradingbot.ml.research.phase22c.hold_chain import get_hold_chain, reset_hold_chain
from tradingbot.ml.research.phase22e.config import (
    BALANCE,
    SYMBOL,
    ValidationWindow,
    configure_production_env,
    data_window_days,
)
from tradingbot.ml.research.phase22e.metrics import compute_extended_metrics, is_range_trade, is_trend_trade


async def run_production_backtest(
    timeframe: str,
    window: ValidationWindow,
    *,
    balance: float = BALANCE,
    spread_pips: float | None = None,
    slippage_pips: float | None = None,
    variable_spread: bool | None = None,
    skip_hold_chain: bool = False,
) -> dict[str, Any]:
    """Run BacktestEngine on exact live pipeline (TradingKernel path)."""
    configure_production_env()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from scripts.backtest_custom_range import entry_in_tehran_range, parse_tehran_dt
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine
    from tradingbot.backtest.models import BacktestResult

    TEHRAN = ZoneInfo("Asia/Tehran")

    if not skip_hold_chain:
        reset_hold_chain()

    now_tehran = datetime.now(TEHRAN)
    days, offset = data_window_days(timeframe, window.start, window.end, now_tehran)

    cfg = load_legacy_config()
    bc = BacktestConfig(
        symbols=[SYMBOL],
        timeframe=timeframe,
        days=days,
        start_offset_days=offset,
        initial_balance=balance,
        use_cache=False,
    )
    if spread_pips is not None:
        bc.spread_pips = spread_pips
    if slippage_pips is not None:
        bc.slippage_pips = slippage_pips
    if variable_spread is not None:
        bc.variable_spread = variable_spread

    t0 = time.perf_counter()
    eng = BacktestEngine(bc, legacy_config=cfg, quiet=True)
    result = await eng.run()
    elapsed = time.perf_counter() - t0

    filtered = [t for t in result.trades if entry_in_tehran_range(t.entry_time, window.start, window.end)]
    range_result = BacktestResult(
        config=bc,
        initial_balance=balance,
        final_balance=balance + sum(t.pnl for t in filtered),
        trades=filtered,
        equity_curve=[
            {"equity": balance + sum(t.pnl for t in filtered[: i + 1])}
            for i in range(len(filtered))
        ]
        if filtered
        else [{"equity": balance}],
    )
    range_metrics = compute_extended_metrics(range_result, timeframe)
    all_metrics = compute_extended_metrics(result, timeframe)
    chain = get_hold_chain().snapshot() if not skip_hold_chain else {}

    # Prefer window-filtered metrics; annotate when fallback needed
    use_metrics = range_metrics if filtered else all_metrics
    metrics_source = "window" if filtered else "full_run"

    signals_blocked = (
        chain.get("ml_hold_total", 0)
        + chain.get("meta_hold", 0)
        + chain.get("riskgate_hold", 0)
    )
    hold_count = max(
        0,
        chain.get("bars_evaluated", 0)
        - chain.get("buy_emitted", 0)
        - chain.get("sell_emitted", 0),
    )

    trend_trades = sum(1 for t in filtered if is_trend_trade(t)) if filtered else all_metrics.get("trend_trades", 0)
    range_trades = sum(1 for t in filtered if is_range_trade(t)) if filtered else all_metrics.get("range_trades", 0)

    return {
        "timeframe": timeframe,
        "window": window.to_dict(),
        "elapsed_sec": round(elapsed, 1),
        "metrics_source": metrics_source,
        "pipeline": "TradingKernel->RegimeRouter->Trend_v41->phase9_9->Calibration->Confidence->Quality->Phase19C->Meta->RiskGate->SimExec",
        "audit": {
            "bars": len(result.equity_curve),
            "bars_in_window": chain.get("bars_evaluated", len(result.equity_curve)),
            "buy_signals": chain.get("buy_emitted", use_metrics.get("buy_trades", 0)),
            "sell_signals": chain.get("sell_emitted", use_metrics.get("sell_trades", 0)),
            "hold_signals": hold_count,
            "trend_trades": trend_trades,
            "range_trades": range_trades,
            "signals_blocked": signals_blocked,
            "trades_executed": len(filtered) if filtered else len(result.trades),
            "hold_chain": chain,
            "note": "hold_chain counts full backtest run; signal counts include per-bar range-zone evaluations",
        },
        "all_trades_count": len(result.trades),
        "window_trades_count": len(filtered),
        "metrics_all": all_metrics,
        "metrics_window": range_metrics,
        "metrics": use_metrics,
        "trades_window": [
            {
                "side": "BUY" if t.is_buy else "SELL",
                "strategy": t.strategy,
                "entry_time": str(t.entry_time),
                "pnl": round(t.pnl, 2),
                "r_multiple": t.r_multiple,
                "reason": t.reason,
            }
            for t in filtered
        ],
        "trades_all": [
            {
                "side": "BUY" if t.is_buy else "SELL",
                "strategy": t.strategy,
                "entry_time": str(t.entry_time),
                "pnl": round(t.pnl, 2),
                "r_multiple": t.r_multiple,
                "reason": t.reason,
            }
            for t in result.trades
        ],
    }
