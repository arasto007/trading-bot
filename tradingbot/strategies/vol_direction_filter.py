"""Phase 48A — VOL_REGIME as direction/quality filter (no independent trades)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.strategies.vol_regime_signal import (
    ATR_PCT_MAX,
    ATR_PCT_MIN,
    prepare_frame,
)
from tradingbot.ml.research.live_l2.edge_discovery_round2 import _volatility_regime_signal


@dataclass(frozen=True)
class VolDirectionAssessment:
    """Read-only VOL filter output — never opens trades."""

    vol_market_ok: bool
    vol_direction: str  # BUY | SELL | HOLD
    vol_strength_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "vol_market_ok": self.vol_market_ok,
            "vol_direction": self.vol_direction,
            "vol_strength_score": round(self.vol_strength_score, 4),
        }


def _strength_score(row: pd.Series, direction: int) -> float:
    atr_pct = float(row.get("atr_pct", np.nan))
    if not np.isfinite(atr_pct):
        return 0.0
    atr_component = max(0.0, 1.0 - abs(atr_pct - 0.5) / max((ATR_PCT_MAX - ATR_PCT_MIN) / 2, 1e-9))
    ema20 = float(row.get("ema20", np.nan))
    ema50 = float(row.get("ema50", np.nan))
    close = float(row.get("close", np.nan))
    if not all(np.isfinite(x) for x in (ema20, ema50, close)) or close <= 0:
        return round(atr_component * 0.5, 4)
    sep_component = min(abs(ema20 - ema50) / max(close * 0.002, 1e-9), 1.0)
    if direction > 0:
        trend_component = min(max((close - ema20) / max(close * 0.001, 1e-9), 0.0), 1.0)
    else:
        trend_component = min(max((ema20 - close) / max(close * 0.001, 1e-9), 0.0), 1.0)
    score = 0.45 * atr_component + 0.35 * sep_component + 0.20 * trend_component
    return round(float(np.clip(score, 0.0, 1.0)), 4)


def evaluate_vol_direction_filter(frame: pd.DataFrame, idx: int) -> VolDirectionAssessment:
    """Evaluate VOL direction filter at bar index on a prepared frame."""
    if frame.empty or idx < 0 or idx >= len(frame):
        return VolDirectionAssessment(False, "HOLD", 0.0)

    row = frame.iloc[idx]
    atr_pct = float(row.get("atr_pct", np.nan))
    market_ok = bool(np.isfinite(atr_pct) and ATR_PCT_MIN <= atr_pct <= ATR_PCT_MAX)

    raw_dir = _volatility_regime_signal(frame, idx)
    if raw_dir not in (1, -1):
        return VolDirectionAssessment(market_ok, "HOLD", 0.0)

    direction_label = "BUY" if int(raw_dir) > 0 else "SELL"
    strength = _strength_score(row, int(raw_dir))
    return VolDirectionAssessment(market_ok, direction_label, strength)


def evaluate_vol_direction_filter_df(df: pd.DataFrame, idx: int) -> VolDirectionAssessment:
    """Evaluate from raw OHLCV (prepares VOL frame internally)."""
    if df is None or df.empty:
        return VolDirectionAssessment(False, "HOLD", 0.0)
    frame = prepare_frame(df.iloc[: idx + 1].copy())
    if frame.empty or idx >= len(frame):
        return VolDirectionAssessment(False, "HOLD", 0.0)
    return evaluate_vol_direction_filter(frame, len(frame) - 1)


def pa_direction_confirmed(pa_direction: str, assessment: VolDirectionAssessment) -> bool:
    """True when VOL market is OK and direction matches PA."""
    if not assessment.vol_market_ok:
        return False
    if assessment.vol_direction not in ("BUY", "SELL"):
        return False
    return assessment.vol_direction == str(pa_direction).upper()
