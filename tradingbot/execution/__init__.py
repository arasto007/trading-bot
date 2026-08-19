"""Realistic MT5-style execution simulation (research layer — not wired to production)."""

from tradingbot.execution.execution_models import (
    ExecutionContext,
    ExecutionProfile,
    ExecutionResult,
    ExecutionScenario,
    FillOutcome,
    LatencyProfile,
    OrderSide,
)
from tradingbot.execution.execution_simulator import ExecutionSimulator

__all__ = [
    "ExecutionContext",
    "ExecutionProfile",
    "ExecutionResult",
    "ExecutionScenario",
    "ExecutionSimulator",
    "FillOutcome",
    "LatencyProfile",
    "OrderSide",
]
