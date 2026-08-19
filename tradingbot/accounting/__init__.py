"""Unified accounting engine — single source of truth for PnL, balance, equity."""

from tradingbot.accounting.broker_constraints import BrokerConstraints, constraints_for_symbol
from tradingbot.accounting.engine import AccountingEngine
from tradingbot.accounting.ledger import AccountingLedger
from tradingbot.accounting.metrics import compute_performance_metrics
from tradingbot.accounting.pnl import calculate_pnl, calculate_pnl_r
from tradingbot.accounting.position_sizing import PositionSizingResult, resolve_position_size

__all__ = [
    "AccountingEngine",
    "AccountingLedger",
    "BrokerConstraints",
    "PositionSizingResult",
    "calculate_pnl",
    "calculate_pnl_r",
    "compute_performance_metrics",
    "constraints_for_symbol",
    "resolve_position_size",
]
