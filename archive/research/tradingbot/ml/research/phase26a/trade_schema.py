"""Completed paper trade record schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CompletedPaperTrade:
    timestamp: str
    symbol: str
    regime: str
    engine: str
    direction: str
    probability: float | None
    confidence: float
    sl: float | None
    tp: float | None
    lot: float
    rr: float | None
    spread: float
    adx: float | None
    rsi: float | None
    atr: float | None
    feature_checksum: str | None
    model_checksum: str | None
    filter_profile: str | None
    decision_source: str | None
    exit_reason: str
    pnl: float
    pnl_r: float
    duration_bars: int
    mae: float
    mfe: float
    entry_price: float | None = None
    exit_price: float | None = None
    exit_timestamp: str | None = None
    timeframe: str = "M5"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
