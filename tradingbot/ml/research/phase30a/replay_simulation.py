"""Replay Phase 29B trades with execution simulation — entries/exits unchanged."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from tradingbot.accounting.ledger import AccountingLedger, ClosedTradeRecord
from tradingbot.accounting.metrics import compute_performance_metrics
from tradingbot.accounting.pnl import calculate_pnl
from tradingbot.execution.execution_costs import session_from_hour
from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile, ExecutionScenario, OrderSide
from tradingbot.execution.execution_simulator import ExecutionSimulator


def _hour_from_ts(ts: str) -> int:
    try:
        return pd.Timestamp(ts).hour
    except Exception:
        return 12


def _simulate_trade_pnl(
    trade: dict[str, Any],
    profile: ExecutionProfile,
    *,
    seed_offset: int = 0,
) -> dict[str, Any]:
    """Apply execution simulation to entry/exit fills without changing trade timing."""
    sim = ExecutionSimulator(ExecutionProfile(**{**profile.__dict__, "seed": profile.seed + seed_offset}))
    direction = str(trade.get("direction", "BUY"))
    side = OrderSide.BUY if direction == "BUY" else OrderSide.SELL
    exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
    lot = float(trade.get("lot", 0.01))
    entry_ref = float(trade.get("entry_price", 0))
    exit_ref = float(trade.get("exit_price", 0))
    symbol = str(trade.get("symbol", "XAUUSD"))

    entry_ctx = ExecutionContext(
        symbol=symbol,
        side=side,
        requested_lot=lot,
        reference_price=entry_ref,
        timestamp=str(trade.get("timestamp", "")),
        session=session_from_hour(_hour_from_ts(str(trade.get("timestamp", "")))),
        atr=float(trade.get("atr", 1.5) or 1.5),
        atr_percentile=float(trade.get("atr_percentile", 50) or 50),
        spread_points=float(trade.get("spread", 0.30) or 0.30),
        liquidity_score=0.7,
        trend_strength=0.5,
    )
    exit_ctx = ExecutionContext(
        symbol=symbol,
        side=exit_side,
        requested_lot=lot,
        reference_price=exit_ref,
        timestamp=str(trade.get("exit_timestamp", trade.get("timestamp", ""))),
        session=session_from_hour(_hour_from_ts(str(trade.get("exit_timestamp", trade.get("timestamp", ""))))),
        atr=entry_ctx.atr,
        atr_percentile=entry_ctx.atr_percentile,
        spread_points=entry_ctx.spread_points,
        liquidity_score=0.7,
        trend_strength=0.5,
    )

    entry_result = sim.simulate(entry_ctx)
    exit_result = sim.simulate(exit_ctx)

    effective_lot = min(entry_result.outcome.filled_lot, exit_result.outcome.filled_lot)
    is_buy = direction == "BUY"
    original_pnl = float(trade.get("pnl", 0))
    simulated_pnl = calculate_pnl(
        entry_result.outcome.fill_price,
        exit_result.outcome.fill_price,
        is_buy=is_buy,
        lot=effective_lot,
        symbol=symbol,
    )

    return {
        **trade,
        "original_pnl": original_pnl,
        "simulated_pnl": round(simulated_pnl, 4),
        "pnl_delta": round(simulated_pnl - original_pnl, 4),
        "entry_fill_price": entry_result.outcome.fill_price,
        "exit_fill_price": exit_result.outcome.fill_price,
        "effective_lot": effective_lot,
        "entry_execution_score": entry_result.outcome.execution_score,
        "exit_execution_score": exit_result.outcome.execution_score,
        "execution_score": round(
            (entry_result.outcome.execution_score + exit_result.outcome.execution_score) / 2, 2
        ),
        "entry_spread": entry_result.outcome.spread_points,
        "exit_spread": exit_result.outcome.spread_points,
        "entry_slippage": entry_result.outcome.slippage_points,
        "exit_slippage": exit_result.outcome.slippage_points,
        "entry_fill_ratio": entry_result.outcome.fill_ratio,
        "exit_fill_ratio": exit_result.outcome.fill_ratio,
        "entry_latency_ms": entry_result.outcome.latency_ms,
        "exit_latency_ms": exit_result.outcome.latency_ms,
        "market_impact": round(
            entry_result.outcome.market_impact_points + exit_result.outcome.market_impact_points, 4
        ),
    }


def replay_trades_with_execution(
    trades: list[dict[str, Any]],
    profile: ExecutionProfile,
    *,
    initial_balance: float = 200.0,
) -> dict[str, Any]:
    simulated_rows = [
        _simulate_trade_pnl(t, profile, seed_offset=i) for i, t in enumerate(trades)
    ]
    ledger = AccountingLedger(initial_balance=initial_balance)
    for row in simulated_rows:
        ledger.apply_close(
            ClosedTradeRecord(
                trade_id=str(row.get("trade_id", "")),
                timestamp=str(row.get("timestamp", "")),
                exit_timestamp=str(row.get("exit_timestamp", "")),
                symbol=str(row.get("symbol", "XAUUSD")),
                direction=str(row.get("direction", "BUY")),
                entry_price=float(row.get("entry_fill_price", row.get("entry_price", 0))),
                exit_price=float(row.get("exit_fill_price", row.get("exit_price", 0))),
                lot=float(row.get("effective_lot", row.get("lot", 0.01))),
                pnl=float(row.get("simulated_pnl", 0)),
                pnl_r=float(row.get("pnl_r", 0)),
            )
        )
    perf = compute_performance_metrics(ledger)
    return {
        "scenario": profile.scenario.value,
        "trade_count": len(simulated_rows),
        "performance": perf,
        "simulated_trades": simulated_rows,
    }


def baseline_performance(trades: list[dict[str, Any]], *, initial_balance: float = 200.0) -> dict[str, Any]:
    ledger = AccountingLedger(initial_balance=initial_balance)
    for t in trades:
        ledger.apply_close(
            ClosedTradeRecord(
                trade_id=str(t.get("trade_id", "")),
                timestamp=str(t.get("timestamp", "")),
                exit_timestamp=str(t.get("exit_timestamp", "")),
                symbol=str(t.get("symbol", "XAUUSD")),
                direction=str(t.get("direction", "BUY")),
                entry_price=float(t.get("entry_price", 0)),
                exit_price=float(t.get("exit_price", 0)),
                lot=float(t.get("lot", 0.01)),
                pnl=float(t.get("pnl", 0)),
                pnl_r=float(t.get("pnl_r", 0)),
            )
        )
    return compute_performance_metrics(ledger)
