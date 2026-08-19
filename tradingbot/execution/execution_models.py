"""Execution simulation domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionScenario(str, Enum):
    NORMAL = "normal"
    HIGH_SPREAD = "high_spread"
    HIGH_SLIPPAGE = "high_slippage"
    HIGH_LATENCY = "high_latency"
    LOW_LIQUIDITY = "low_liquidity"
    NEWS = "news"
    FLASH_CRASH = "flash_crash"
    WEEKEND = "weekend"


class LatencyProfile(str, Enum):
    NORMAL = "normal"
    FAST_VPS = "fast_vps"
    SLOW_VPS = "slow_vps"


@dataclass(frozen=True)
class ExecutionProfile:
    """Tunable execution environment profile."""

    scenario: ExecutionScenario = ExecutionScenario.NORMAL
    latency_profile: LatencyProfile = LatencyProfile.NORMAL
    spread_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    liquidity_multiplier: float = 1.0
    impact_multiplier: float = 1.0
    delay_multiplier: float = 1.0
    requote_probability: float = 0.02
    partial_fill_enabled: bool = True
    seed: int = 42


@dataclass
class ExecutionContext:
    """Market state at order submission time."""

    symbol: str
    side: OrderSide
    requested_lot: float
    reference_price: float
    timestamp: str
    session: str = "London"
    atr: float = 1.0
    atr_percentile: float = 50.0
    spread_points: float = 0.30
    volatility_regime: str = "normal"
    trend_strength: float = 0.5
    is_news_window: bool = False
    is_weekend: bool = False
    is_fast_market: bool = False
    is_slow_market: bool = False
    liquidity_score: float = 0.7
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FillOutcome:
    fill_price: float
    filled_lot: float
    fill_ratio: float
    spread_points: float
    slippage_points: float
    slippage_sign: int
    latency_ms: float
    queue_delay_ms: float
    market_impact_points: float
    requoted: bool
    partial_fill: bool
    execution_score: float


@dataclass(frozen=True)
class ExecutionResult:
    context: ExecutionContext
    outcome: FillOutcome
    total_cost_points: float
    effective_price: float
    diagnostics: dict[str, Any]
