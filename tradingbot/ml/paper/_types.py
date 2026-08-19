"""Paper trading configuration and trade records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class SignalMode(str, Enum):
    ML = "ml"
    HYBRID = "hybrid"
    RULE = "rule"
    AB = "ab"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


def new_trade_id() -> str:
    return str(uuid4())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PaperTrade:
    trade_id: str
    timestamp: str
    symbol: str
    direction: int
    signal_source: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_unit: float
    status: str = TradeStatus.OPEN.value
    exit_price: float = 0.0
    exit_timestamp: str = ""
    r_multiple: float = 0.0
    slippage: float = 0.0
    spread_cost: float = 0.0
    session: str = "unknown"
    bars_held: int = 0
    exit_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperConfig:
    tp_r: float = 2.0
    sl_r: float = 1.0
    risk_per_trade_r: float = 1.0
    initial_balance_r: float = 100.0
    compounding: bool = False
    future_window_bars: int = 72
    atr_period: int = 14
    min_score: float = 0.60
    ml_threshold: float = 0.50
    deterministic: bool = False
    random_seed: int = 42

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
