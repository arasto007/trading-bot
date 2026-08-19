"""Phase 15B — UnifiedSignal to TradingSignal mapping (no information loss)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.domain.signal_helpers import compute_sl_tp
from tradingbot.ml.phase15a.unified_signal import UnifiedSignal

STRATEGY_NAME = "ml_kernel_15b"


def _direction_enum(direction: str) -> SignalDirection:
    if direction == "BUY":
        return SignalDirection.BUY
    if direction == "SELL":
        return SignalDirection.SELL
    return SignalDirection.HOLD


def _trace_id(unified: UnifiedSignal) -> str:
    raw = unified.checksum or unified.compute_checksum()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def map_unified_to_trading_signal(
    unified: UnifiedSignal,
    market: MarketKey,
    df: pd.DataFrame,
    *,
    config: dict[str, Any] | None = None,
) -> TradingSignal:
    """Map canonical ML signal to kernel TradingSignal preserving all fields in metadata."""
    direction = _direction_enum(unified.direction)
    signal_int = 1 if direction == SignalDirection.BUY else -1 if direction == SignalDirection.SELL else 0

    sl = unified.sl
    tp = unified.tp
    extra: dict[str, Any] = {}
    if (sl is None or tp is None) and not df.empty and signal_int != 0:
        sl_v, tp_v, extra = compute_sl_tp(
            df, signal_int, unified.confidence,
            symbol=market.symbol, strategy_name=STRATEGY_NAME, timeframe=market.timeframe, config=config,
        )
        sl = sl if sl is not None else sl_v
        tp = tp if tp is not None else tp_v

    trace_id = _trace_id(unified)
    metadata: dict[str, Any] = {
        "signal_source": "ml_kernel",
        "engine_name": unified.engine,
        "regime": unified.regime,
        "quality": unified.quality,
        "risk_percent": unified.risk,
        "reason": list(unified.reason),
        "trace": list(unified.trace),
        "trace_id": trace_id,
        "unified_checksum": unified.checksum,
        "unified_timestamp": unified.timestamp,
        "ml_kernel_version": "15b",
        **extra,
    }

    return TradingSignal(
        direction=direction,
        confidence=float(unified.confidence),
        symbol=market.symbol,
        timeframe=market.timeframe,
        strategy_name=STRATEGY_NAME,
        stop_loss=sl,
        take_profit=tp,
        metadata=metadata,
    )


def trading_signal_schema() -> dict[str, Any]:
    return {
        "direction": ["BUY", "SELL", "HOLD"],
        "fields": [
            "confidence", "risk_percent", "stop_loss", "take_profit",
            "reason", "trace_id", "engine_name", "regime", "timestamp",
        ],
        "metadata_preserves": [
            "engine_name", "regime", "quality", "risk_percent",
            "reason", "trace", "trace_id", "unified_checksum",
        ],
    }
