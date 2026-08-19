"""VOL_REGIME signal generator — ATR2.5_RR0.8 live core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    _prepare_frame_round2,
    _volatility_regime_signal,
)

STRATEGY_ID = "VOL_REGIME"
CONFIG_ID = "ATR2.5_RR0.8"
DEFAULT_ATR_SL_MULT = 2.5
DEFAULT_TP_RR = 0.8
DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
ATR_PCT_MIN = 0.30
ATR_PCT_MAX = 0.70


@dataclass(frozen=True)
class VolRegimeSignal:
    """Read-only signal output for VOL_REGIME hypothesis."""

    direction: int  # 1=BUY, -1=SELL
    bar_index: int
    timestamp: pd.Timestamp
    atr_pct: float
    ema20: float
    ema50: float
    close: float
    config_id: str = CONFIG_ID
    hypothesis_id: str = STRATEGY_ID
    atr_sl_mult: float = DEFAULT_ATR_SL_MULT
    tp_rr: float = DEFAULT_TP_RR

    @property
    def side(self) -> str:
        return "BUY" if self.direction > 0 else "SELL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "config_id": self.config_id,
            "direction": self.direction,
            "side": self.side,
            "bar_index": self.bar_index,
            "timestamp_utc": self.timestamp.isoformat(),
            "atr_pct": round(self.atr_pct, 4),
            "ema20": self.ema20,
            "ema50": self.ema50,
            "close": self.close,
            "atr_sl_mult": self.atr_sl_mult,
            "tp_rr": self.tp_rr,
            "research_only": True,
            "production_deploy": "BLOCKED",
        }


def prepare_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Build indicator frame required for VOL_REGIME evaluation."""
    return _prepare_frame_round2(candles)


def evaluate_at_index(frame: pd.DataFrame, idx: int) -> VolRegimeSignal | None:
    """Evaluate VOL_REGIME at a single bar index (read-only)."""
    if idx < 0 or idx >= len(frame):
        return None
    direction = _volatility_regime_signal(frame, idx)
    if direction not in (1, -1):
        return None
    row = frame.iloc[idx]
    return VolRegimeSignal(
        direction=int(direction),
        bar_index=idx,
        timestamp=pd.Timestamp(frame.index[idx]),
        atr_pct=float(row["atr_pct"]),
        ema20=float(row["ema20"]),
        ema50=float(row["ema50"]),
        close=float(row["close"]),
    )


def scan_signals(
    frame: pd.DataFrame,
    *,
    start_idx: int = 500,
    end_idx: int | None = None,
    stride: int = 3,
) -> list[VolRegimeSignal]:
    """Scan frame for VOL_REGIME signals (research / backtest helper)."""
    if frame.empty:
        return []
    end = len(frame) - 1 if end_idx is None else min(end_idx, len(frame) - 1)
    out: list[VolRegimeSignal] = []
    for idx in range(max(0, start_idx), end + 1, max(1, stride)):
        sig = evaluate_at_index(frame, idx)
        if sig is not None:
            out.append(sig)
    return out


def signal_metadata() -> dict[str, Any]:
    """Static strategy metadata for integration planning."""
    return {
        "strategy_id": STRATEGY_ID,
        "config_id": CONFIG_ID,
        "title_en": "Volatility regime: ATR percentile sweet spot 30-70%",
        "title_fa": "رژیم نوسان ATR 30-70%",
        "symbol": DEFAULT_SYMBOL,
        "timeframe": DEFAULT_TIMEFRAME,
        "atr_sl_mult": DEFAULT_ATR_SL_MULT,
        "tp_rr": DEFAULT_TP_RR,
        "atr_pct_range": [ATR_PCT_MIN, ATR_PCT_MAX],
        "ml_filter": "SKIP",
        "backtest_pf_l27": 1.4262,
        "shadow_pf_l3": 1.4037,
        "production_deploy": "LIVE",
    }
