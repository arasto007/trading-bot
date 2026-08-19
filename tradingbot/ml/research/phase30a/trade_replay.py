"""Replay Phase 29B trades through execution simulator — entries/exits unchanged, execution costs adjusted."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pandas as pd

from tradingbot.accounting.ledger import AccountingLedger, ClosedTradeRecord
from tradingbot.accounting.metrics import compute_performance_metrics
from tradingbot.execution.execution_costs import session_from_hour
from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile, ExecutionScenario, OrderSide
from tradingbot.execution.execution_simulator import ExecutionSimulator
from tradingbot.execution.fill_model import fill_statistics


def _parse_hour(ts: str) -> int:
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
    direction = str(trade.get("direction", "BUY"))
    is_buy = direction == "BUY"
    entry = float(trade.get("entry_price", 0))
    exit_px = float(trade.get("exit_price", 0))
    lot = float(trade.get("lot", 0.01))
    symbol = str(trade.get("symbol", "XAUUSD"))
    hour = _parse_hour(str(trade.get("timestamp", "")))

    entry_ctx = ExecutionContext(
        symbol=symbol,
        side=OrderSide.BUY if is_buy else OrderSide.SELL,
        requested_lot=lot,
        reference_price=entry,
        timestamp=str(trade.get("timestamp", "")),
        session=session_from_hour(hour),
        atr=float(trade.get("atr", 1.5) or 1.5),
        atr_percentile=float(trade.get("atr_percentile", 50) or 50),
        spread_points=float(trade.get("spread", 0.30) or 0.30),
        liquidity_score=0.7,
        trend_strength=0.5,
    )
    exit_ctx = ExecutionContext(
        symbol=symbol,
        side=OrderSide.SELL if is_buy else OrderSide.BUY,
        requested_lot=lot,
        reference_price=exit_px,
        timestamp=str(trade.get("exit_timestamp", trade.get("timestamp", ""))),
        session=session_from_hour(_parse_hour(str(trade.get("exit_timestamp", trade.get("timestamp", ""))))),
        atr=entry_ctx.atr,
        atr_percentile=entry_ctx.atr_percentile,
        spread_points=entry_ctx.spread_points,
        liquidity_score=0.7,
    )

    sim = ExecutionSimulator(replace(profile, seed=profile.seed + seed_offset))
    entry_result = sim.simulate(entry_ctx)
    exit_result = sim.simulate(exit_ctx)

    eff_lot = min(lot, entry_result.outcome.filled_lot, exit_result.outcome.filled_lot)
    eff_lot = max(0.001, eff_lot)

    from tradingbot.accounting.pnl import calculate_pnl

    ideal_pnl = float(trade.get("pnl", 0))
    sim_pnl = calculate_pnl(
        entry_result.outcome.fill_price,
        exit_result.outcome.fill_price,
        is_buy=is_buy,
        lot=eff_lot,
        symbol=symbol,
    )

    return {
        **trade,
        "ideal_pnl": ideal_pnl,
        "simulated_pnl": round(sim_pnl, 4),
        "pnl_delta": round(sim_pnl - ideal_pnl, 4),
        "entry_fill": entry_result.outcome.fill_price,
        "exit_fill": exit_result.outcome.fill_price,
        "filled_lot": eff_lot,
        "entry_execution_score": entry_result.outcome.execution_score,
        "exit_execution_score": exit_result.outcome.execution_score,
        "execution_score": round((entry_result.outcome.execution_score + exit_result.outcome.execution_score) / 2, 2),
        "entry_spread": entry_result.outcome.spread_points,
        "entry_slippage": entry_result.outcome.slippage_points,
        "entry_latency_ms": entry_result.outcome.latency_ms,
        "fill_ratio": entry_result.outcome.fill_ratio,
        "partial_fill": entry_result.outcome.partial_fill,
        "requoted": entry_result.outcome.requoted,
        "market_impact": entry_result.outcome.market_impact_points,
    }


def replay_trades_with_execution(
    trades: list[dict[str, Any]],
    profile: ExecutionProfile,
    *,
    initial_balance: float = 200.0,
) -> dict[str, Any]:
    simulated: list[dict[str, Any]] = []
    for i, trade in enumerate(trades):
        simulated.append(_simulate_trade_pnl(trade, profile, seed_offset=i))

    ledger = AccountingLedger(initial_balance=initial_balance)
    for t in simulated:
        ledger.apply_close(
            ClosedTradeRecord(
                trade_id=str(t.get("trade_id", "")),
                timestamp=str(t.get("timestamp", "")),
                exit_timestamp=str(t.get("exit_timestamp", "")),
                symbol=str(t.get("symbol", "XAUUSD")),
                direction=str(t.get("direction", "BUY")),
                entry_price=float(t.get("entry_fill", t.get("entry_price", 0))),
                exit_price=float(t.get("exit_fill", t.get("exit_price", 0))),
                lot=float(t.get("filled_lot", t.get("lot", 0.01))),
                pnl=float(t["simulated_pnl"]),
                pnl_r=float(t.get("pnl_r", 0)),
            )
        )

    perf = compute_performance_metrics(ledger)
    fills = [
        {
            "fill_ratio": t["fill_ratio"],
            "requoted": t["requoted"],
            "partial_fill": t["partial_fill"],
        }
        for t in simulated
    ]
    scores = [float(t["execution_score"]) for t in simulated]

    return {
        "scenario": profile.scenario.value,
        "trade_count": len(simulated),
        "performance": perf,
        "trades": simulated,
        "fill_stats": fill_statistics(fills),
        "execution_quality": {
            "mean_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "min_score": round(min(scores), 2) if scores else 0,
            "max_score": round(max(scores), 2) if scores else 0,
            "p50_score": round(sorted(scores)[len(scores) // 2], 2) if scores else 0,
        },
    }
