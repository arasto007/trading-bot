"""مدل‌های بک‌تست — پوزیشن مجازی، معامله‌ی بسته‌شده، نتیجه."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tradingbot.domain.position_logic import contract_size


@dataclass
class VirtualPosition:
    """پوزیشن شبیه‌سازی‌شده در بک‌تست."""

    ticket: int
    symbol: str
    is_buy: bool
    entry_price: float
    volume: float
    sl: float
    tp: float
    entry_index: int
    entry_time: datetime
    strategy: str = "combined"
    initial_risk: float = 0.0
    original_volume: float = 0.0
    realized_pnl: float = 0.0          # سود ناشی از بستن جزئی
    partial_hits: list[bool] = field(default_factory=list)
    commission_paid: float = 0.0
    entry_features: dict[str, float] = field(default_factory=dict)
    entry_sl: float = 0.0
    pm_breakeven_done: bool = False
    pm_partial_done: bool = False
    pm_trailing_active: bool = False
    pm_bars_held: int = 0
    pm_last_bar_index: int = -1

    def __post_init__(self) -> None:
        if self.original_volume <= 0:
            self.original_volume = self.volume

    def unrealized_pnl(self, price: float) -> float:
        direction = 1.0 if self.is_buy else -1.0
        return (price - self.entry_price) * direction * contract_size(self.symbol) * self.volume

    def pnl_for_volume(self, price: float, volume: float) -> float:
        direction = 1.0 if self.is_buy else -1.0
        return (price - self.entry_price) * direction * contract_size(self.symbol) * volume


@dataclass
class ClosedTrade:
    symbol: str
    is_buy: bool
    entry_price: float
    exit_price: float
    volume: float
    entry_time: datetime
    exit_time: datetime
    pnl: float                 # شامل سودهای جزئی + هزینه‌ها
    reason: str                # sl | tp | trailing | emergency | partial | end
    strategy: str = "combined"
    exit_index: int = 0
    entry_sl: float = 0.0
    initial_risk: float = 0.0
    entry_features: dict[str, float] = field(default_factory=dict)
    r_multiple: float = 0.0


@dataclass
class BacktestResult:
    config: Any
    initial_balance: float
    final_balance: float
    trades: list[ClosedTrade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
