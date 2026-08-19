"""Phase 22F — rapid production-path backtest runner with trace."""

from __future__ import annotations

import time
from typing import Any

from tradingbot.ml.research.phase22c.hold_chain import get_hold_chain, reset_hold_chain
from tradingbot.ml.research.phase22f.config import BALANCE, SYMBOL, RapidDataset, configure_research_env, data_window_days
from tradingbot.ml.research.phase22f.trace import TraceCollector, install_trace_hooks, reset_trace


async def run_rapid_backtest(
    timeframe: str,
    dataset: RapidDataset,
    *,
    balance: float = BALANCE,
    blocked_events_limit: int | None = 500,
) -> dict[str, Any]:
    configure_research_env()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from scripts.backtest_custom_range import entry_in_tehran_range
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine
    from tradingbot.backtest.models import BacktestResult
    from tradingbot.ml.research.phase22e.metrics import compute_extended_metrics, is_range_trade, is_trend_trade

    TEHRAN = ZoneInfo("Asia/Tehran")
    reset_hold_chain()
    trace = reset_trace(timeframe)
    install_trace_hooks(trace)

    now_tehran = datetime.now(TEHRAN)
    days, offset = data_window_days(timeframe, dataset.start, dataset.end, now_tehran)

    cfg = load_legacy_config()
    bc = BacktestConfig(
        symbols=[SYMBOL],
        timeframe=timeframe,
        days=days,
        start_offset_days=offset,
        initial_balance=balance,
        use_cache=True,
    )

    t0 = time.perf_counter()
    eng = BacktestEngine(bc, legacy_config=cfg, quiet=True)
    result = await eng.run()
    elapsed = time.perf_counter() - t0

    filtered = [t for t in result.trades if entry_in_tehran_range(t.entry_time, dataset.start, dataset.end)]
    use_trades = filtered if filtered else result.trades
    stub = BacktestResult(
        config=bc,
        initial_balance=balance,
        final_balance=balance + sum(t.pnl for t in use_trades),
        trades=use_trades,
        equity_curve=[
            {"equity": balance + sum(t.pnl for t in use_trades[: i + 1])}
            for i in range(len(use_trades))
        ]
        if use_trades
        else [{"equity": balance}],
    )
    metrics = compute_extended_metrics(stub, timeframe)
    chain = get_hold_chain().snapshot()
    stages = chain.get("ml_hold_stages") or {}
    bars = chain.get("bars_evaluated", 0)
    trace.model_pass = chain.get("buy_emitted", 0) + chain.get("sell_emitted", 0)
    trace.calibration_pass = bars - stages.get("decision_hold", 0) - stages.get("calibration_hold", 0)
    trace.quality_pass = trace.calibration_pass - stages.get("trade_quality_hold", 0)
    trace.rsi_pass = trace.quality_pass - stages.get("rsi_filter_hold", 0)
    trace.adx_pass = trace.rsi_pass - stages.get("adx_filter_hold", 0)
    trace.meta_pass = trace.adx_pass - chain.get("meta_hold", 0)

    durations = []
    for t in use_trades:
        if t.entry_time and t.exit_time:
            try:
                delta = t.exit_time - t.entry_time
                durations.append(delta.total_seconds() / 60.0)
            except Exception:
                pass
    avg_duration_min = round(sum(durations) / len(durations), 2) if durations else 0.0

    buys = sum(1 for t in use_trades if t.is_buy)
    sells = len(use_trades) - buys
    n_sig = chain.get("buy_emitted", 0) + chain.get("sell_emitted", 0) + chain.get("ml_hold_stages", {}).get("decision_hold", 0)

    return {
        "timeframe": timeframe,
        "dataset": dataset.to_dict(),
        "elapsed_sec": round(elapsed, 1),
        "trades": len(use_trades),
        "metrics": metrics,
        "hold_chain": chain,
        "trace": trace.snapshot_funnel(),
        "summary": {
            "trades": len(use_trades),
            "buy_pct": round(buys / max(len(use_trades), 1) * 100, 2),
            "sell_pct": round(sells / max(len(use_trades), 1) * 100, 2),
            "hold_pct": round(chain.get("ml_hold_stages", {}).get("decision_hold", 0) / max(chain.get("bars_evaluated", 1), 1) * 100, 2),
            "profit_factor": metrics.get("profit_factor"),
            "expectancy": metrics.get("expectancy"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "avg_trade_duration_min": avg_duration_min,
            "signals_reaching_riskgate": trace.riskgate_reached,
            "signals_blocked_riskgate": trace.riskgate_reached - trace.riskgate_pass,
            "riskgate_block_reasons": dict(trace.riskgate_block_reasons),
            "model_utilization": dict(trace.engine_counts),
            "regime_distribution": dict(trace.regime_counts),
            "trend_trades": sum(1 for t in use_trades if is_trend_trade(t)),
            "range_trades": sum(1 for t in use_trades if is_range_trade(t)),
        },
        "trades_detail": [
            {
                "side": "BUY" if t.is_buy else "SELL",
                "entry_time": str(t.entry_time),
                "exit_time": str(t.exit_time),
                "pnl": round(t.pnl, 2),
                "r_multiple": t.r_multiple,
                "strategy": t.strategy,
                "reason": t.reason,
                "entry_sl": t.entry_sl,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
            }
            for t in use_trades
        ],
        "blocked_events": [
            e.to_dict()
            for e in (
                trace.blocked_events
                if blocked_events_limit is None
                else trace.blocked_events[:blocked_events_limit]
            )
        ],
        "forensic_events": trace.forensic_events,
        "blocked_events_total": len(trace.blocked_events),
    }
