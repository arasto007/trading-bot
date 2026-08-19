"""Dataset schema constants and row structure for Phase 3 supervised learning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

DATASET_SCHEMA_VERSION = "1.0"
DEFAULT_FUTURE_WINDOW_M5 = 72  # 6 hours on M5
DEFAULT_RR_TP = 2.0  # TP = 2R
DEFAULT_RR_SL = 1.0  # SL = 1R

SAMPLE_EVENT_TYPES: tuple[str, ...] = (
    "bos",
    "choch",
    "liquidity_sweep",
    "fvg",
    "order_block",
    "session_transition",
    "trading_session",
)

META_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "timeframe",
    "event_type",
    "event_time",
    "event_id",
    "timeframe_role",
    "entry_price",
    "direction",
    "stop_loss",
    "take_profit",
    "label",
    "future_window_bars",
    "tp_hit",
    "sl_hit",
    "mfe",
    "mae",
    "future_return",
    "risk_unit",
    "split",
    "dataset_schema_version",
)


class Label(IntEnum):
    SL_FIRST = 0
    TP_FIRST = 1
    NO_RESOLUTION = -1


@dataclass
class DatasetBuildConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    future_window_bars: int = DEFAULT_FUTURE_WINDOW_M5
    tp_r_multiple: float = DEFAULT_RR_TP
    sl_r_multiple: float = DEFAULT_RR_SL
    atr_period: int = 14
    event_timeframes: tuple[str, ...] = ("M5", "M15")
    include_session_transitions: bool = True
    purge_bars: int = DEFAULT_FUTURE_WINDOW_M5


@dataclass
class LabeledSample:
    timestamp: str
    symbol: str
    timeframe: str
    event_type: str
    event_time: str
    event_id: str
    timeframe_role: str
    entry_price: float
    direction: int
    stop_loss: float
    take_profit: float
    label: int
    future_window_bars: int
    tp_hit: bool
    sl_hit: bool
    mfe: float
    mae: float
    future_return: float
    risk_unit: float
    features: dict[str, float] = field(default_factory=dict)
    split: str = ""

    def to_row(self) -> dict[str, Any]:
        row = {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "event_type": self.event_type,
            "event_time": self.event_time,
            "event_id": self.event_id,
            "timeframe_role": self.timeframe_role,
            "entry_price": self.entry_price,
            "direction": self.direction,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "label": int(self.label),
            "future_window_bars": self.future_window_bars,
            "tp_hit": self.tp_hit,
            "sl_hit": self.sl_hit,
            "mfe": self.mfe,
            "mae": self.mae,
            "future_return": self.future_return,
            "risk_unit": self.risk_unit,
            "split": self.split,
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
        }
        row.update(self.features)
        return row
