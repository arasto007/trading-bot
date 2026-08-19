"""Research-only trade exit simulation on historical candles."""

from __future__ import annotations

from tradingbot.services.paper_trade_exit import resolve_paper_trade_exit as simulate_trade_exit

__all__ = ["simulate_trade_exit"]
