"""Repository map of PnL/accounting implementations."""

from __future__ import annotations

from typing import Any

CANONICAL_ENGINE = "tradingbot.accounting.engine.AccountingEngine"
CANONICAL_PNL = "tradingbot.accounting.pnl.calculate_pnl"
CANONICAL_SIZING = "tradingbot.accounting.position_sizing.resolve_position_size"

ENGINE_MAP: dict[str, Any] = {
    "phase": "28F",
    "canonical_engine": CANONICAL_ENGINE,
    "canonical_pnl": CANONICAL_PNL,
    "canonical_sizing": CANONICAL_SIZING,
    "unified_consumers": [
        "tradingbot.ml.research.phase25b.replay_portfolio.ReplayPortfolioTracker",
        "tradingbot.ml.research.phase28d.trade_builder.trades_from_replay_meta",
        "tradingbot.services.paper_trade_recorder.PaperTradeRecorder",
        "tradingbot.accounting.metrics.compute_performance_metrics",
    ],
    "deprecated_duplicates": [
        {
            "path": "tradingbot.ml.research.phase28d.trade_builder.build_hybrid_trades",
            "issue": "Previously re-resolved exits with full candle history",
            "status": "replaced_by_accounting_export",
        },
        {
            "path": "tradingbot.ml.research.phase25b.replay_portfolio._realized_pnl",
            "issue": "Local PnL accumulator diverged from trade log",
            "status": "replaced_by_AccountingEngine",
        },
        {
            "path": "tradingbot.ml.research.phase28d.metrics.build_equity_curves",
            "issue": "Independent balance rebuild",
            "status": "should_consume_accounting_curves",
        },
        {
            "path": "tradingbot.ml.research.phase26b.analyzers._equity_curve",
            "issue": "Duplicate closed-trade equity aggregation",
            "status": "legacy_aggregation",
        },
        {
            "path": "tradingbot.ml.paper.virtual_account.apply_pnl",
            "issue": "Separate balance mutator (ML paper)",
            "status": "not_unified_research_only",
        },
        {
            "path": "tradingbot.ml.backtest.state.BacktestState",
            "issue": "Separate ML backtest equity",
            "status": "not_unified_research_only",
        },
    ],
    "retained_specialized": [
        {
            "path": "tradingbot.backtest.broker.SimulatedBroker",
            "reason": "Bar-by-bar backtest with commission and floating equity",
            "note": "Should delegate PnL formula to accounting.pnl",
        },
        {
            "path": "tradingbot.services.exit_policy._pnl",
            "reason": "Exit walk-forward simulation (delegates to accounting.pnl)",
        },
    ],
}


def build_engine_map() -> dict[str, Any]:
    return dict(ENGINE_MAP)


def build_duplicate_report() -> dict[str, Any]:
    return {
        "phase": "28F",
        "pre_unification_mismatch_usd": 1005.97,
        "root_cause": [
            "trade_builder used full-history exit resolution",
            "replay_portfolio used bar-by-bar candle slice",
            "two independent balance accumulators",
            "fixed 0.01 lot ignored dynamic sizing",
        ],
        "resolution": [
            "AccountingEngine is single balance/PnL mutator",
            "ReplayPortfolioTracker delegates all closes to AccountingEngine",
            "trade_builder reads accounting export — no re-resolution",
            "Dynamic sizing via resolve_position_size with MIN_LOT_LIMIT reporting",
        ],
        "duplicates": ENGINE_MAP["deprecated_duplicates"],
    }
