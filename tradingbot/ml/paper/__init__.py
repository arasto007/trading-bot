"""Phase 11 — kernel paper trading exports."""

from tradingbot.ml.paper.config import PaperTradingConfig, validate_frozen_model
from tradingbot.ml.paper.paper_engine import KernelPaperEngine, PaperRunResult
from tradingbot.ml.paper.paper_execution import PaperExecutionEngine, VirtualOrder
from tradingbot.ml.paper.performance import compute_performance
from tradingbot.ml.paper.portfolio_manager import PortfolioManager
from tradingbot.ml.paper.session_analyzer import analyze_sessions
from tradingbot.ml.paper.trade_lifecycle import PaperTrade, TradeLifecycle
from tradingbot.ml.paper.virtual_account import VirtualAccount

# Phase 6.2 offline engine remains available
from tradingbot.ml.paper.engine import PaperTradingEngine

__all__ = [
    "KernelPaperEngine",
    "PaperExecutionEngine",
    "PaperRunResult",
    "PaperTrade",
    "PaperTradingConfig",
    "PaperTradingEngine",
    "PortfolioManager",
    "TradeLifecycle",
    "VirtualAccount",
    "VirtualOrder",
    "analyze_sessions",
    "compute_performance",
    "validate_frozen_model",
]
