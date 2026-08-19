"""Phase 4A — Adaptive quality scoring engine (replaces AND-gate chain)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    _multi_tf_trend_signal,
    _volatility_regime_signal,
)
from tradingbot.strategies.adaptive_regime import (
    MIN_EMA_SEP,
    MIN_H1_TREND,
    _bar_open_hour_utc,
    _disable_high_vol_for_micro,
    _ema_sep_ok,
    _h1_aligned,
    _maybe_log_micro_high_vol_blocked,
    _resolve_account_tier_for_kill_switch,
    classify_regime,
)
from tradingbot.services.rejection_events import log_rejection_event, row_context

DEFAULT_SYMBOL = "XAUUSD"
LONDON_HOURS = (7, 12)
ATR_BAND = (0.30, 0.70)
TRADEABLE_MIN = 70
WATCHLIST_MIN = 50


@dataclass(frozen=True)
class QualityScoreResult:
    quality_score: int
    score_components: dict[str, int]
    tier: str  # reject | watchlist | tradeable
    direction: int | None

    def to_telemetry(self) -> dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "score_components": dict(self.score_components),
            "quality_tier": self.tier,
        }


def quality_engine_enabled() -> bool:
    raw = os.getenv("ADAPTIVE_QUALITY_ENGINE", "").lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    try:
        from tradingbot.config.live import get_live_config

        return bool(get_live_config().get("ADAPTIVE_QUALITY_ENGINE", False))
    except Exception:
        return False


def _is_london(bar_open: pd.Timestamp) -> bool:
    hour = _bar_open_hour_utc(bar_open)
    return LONDON_HOURS[0] <= hour < LONDON_HOURS[1]


def _atr_in_band(row: pd.Series) -> bool:
    atr_pct = float(row.get("atr_pct", np.nan))
    return np.isfinite(atr_pct) and ATR_BAND[0] <= atr_pct <= ATR_BAND[1]


def _vol_component(frame: pd.DataFrame, idx: int, direction: int) -> int:
    """Full vol signal = 15; partial structure credit when ATR in band."""
    row = frame.iloc[idx]
    if not _atr_in_band(row):
        return 0
    vol_dir = _volatility_regime_signal(frame, idx)
    if vol_dir == direction:
        return 15
    ema20, ema50, close = float(row["ema20"]), float(row["ema50"]), float(row["close"])
    if not all(np.isfinite(x) for x in (ema20, ema50, close)):
        return 4
    if direction > 0 and ema20 > ema50:
        return 8 if close <= ema20 else 4
    if direction < 0 and ema20 < ema50:
        return 8 if close >= ema20 else 4
    return 4


def resolve_candidate_direction(frame: pd.DataFrame, idx: int) -> int | None:
    """Direction from MTF/VOL legs (OR precedence: confluence > mtf > vol)."""
    mtf_dir = _multi_tf_trend_signal(frame, idx)
    row = frame.iloc[idx]
    atr_pct = float(row.get("atr_pct", np.nan))
    vol_dir = (
        _volatility_regime_signal(frame, idx)
        if np.isfinite(atr_pct) and ATR_BAND[0] <= atr_pct <= ATR_BAND[1]
        else None
    )
    if mtf_dir in (1, -1) and vol_dir in (1, -1) and mtf_dir == vol_dir:
        return int(mtf_dir)
    if mtf_dir in (1, -1):
        return int(mtf_dir)
    if vol_dir in (1, -1):
        return int(vol_dir)
    return None


def compute_quality_score(
    frame: pd.DataFrame,
    idx: int,
    direction: int,
    *,
    bar_open: pd.Timestamp | None = None,
) -> QualityScoreResult:
    row = frame.iloc[idx]
    ts = bar_open or pd.Timestamp(frame.index[idx])

    h1 = 30 if (not MIN_H1_TREND or _h1_aligned(row, direction)) else 0
    atr = 20 if _atr_in_band(row) else 0
    ema = 20 if _ema_sep_ok(row) else 0
    session = 15 if _is_london(ts) else 0
    vol = _vol_component(frame, idx, direction)

    components = {"h1": h1, "atr": atr, "ema": ema, "session": session, "vol": vol}
    total = sum(components.values())
    if total >= TRADEABLE_MIN:
        tier = "tradeable"
    elif total >= WATCHLIST_MIN:
        tier = "watchlist"
    else:
        tier = "reject"

    return QualityScoreResult(
        quality_score=total,
        score_components=components,
        tier=tier,
        direction=direction,
    )


def evaluate_quality_at_index(
    frame: pd.DataFrame,
    idx: int,
    *,
    log_rejections: bool = True,
) -> tuple[QualityScoreResult | None, dict[str, Any]]:
    """
    Quality-engine path for adaptive regime.

    Returns (score_result, context) where score_result is set when tier=tradeable
    and a direction exists. Hard kills (NO_TRADE, MICRO+HIGH_VOL) still apply.
    """
    if idx < 0 or idx >= len(frame):
        return None, {}

    row = frame.iloc[idx]
    ctx = row_context(row)
    bar_open = pd.Timestamp(frame.index[idx])
    regime = classify_regime(row)
    ctx["regime"] = regime
    atr_pct = float(row["atr_pct"]) if np.isfinite(float(row.get("atr_pct", np.nan))) else 0.5

    if (
        regime == "HIGH_VOLATILITY"
        and _disable_high_vol_for_micro()
        and _resolve_account_tier_for_kill_switch() == "MICRO"
    ):
        _maybe_log_micro_high_vol_blocked(atr_pct, idx)
        if log_rejections:
            log_rejection_event(
                stage="REGIME",
                direction=None,
                reason="MICRO high-vol kill switch",
                context={**ctx, "atr_pct": round(atr_pct, 4), "account_tier": "MICRO"},
                symbol=DEFAULT_SYMBOL,
            )
        return None, {**ctx, "reject_reason": "MICRO_HIGH_VOL"}

    if regime == "NO_TRADE":
        if log_rejections:
            log_rejection_event(
                stage="REGIME",
                direction=None,
                reason="regime=NO_TRADE",
                context=ctx,
                symbol=DEFAULT_SYMBOL,
            )
        return None, {**ctx, "reject_reason": "NO_TRADE"}

    direction = resolve_candidate_direction(frame, idx)
    if direction is None:
        if log_rejections:
            log_rejection_event(
                stage="QUALITY",
                direction=None,
                reason="no_direction_candidate",
                context={**ctx, "atr_pct": round(atr_pct, 4)},
                symbol=DEFAULT_SYMBOL,
            )
        return None, {**ctx, "reject_reason": "NO_DIRECTION"}

    score = compute_quality_score(frame, idx, direction, bar_open=bar_open)
    ctx.update(score.to_telemetry())

    if score.tier == "reject":
        if log_rejections:
            log_rejection_event(
                stage="QUALITY",
                direction="BUY" if direction > 0 else "SELL",
                reason=f"quality_score={score.quality_score}<{WATCHLIST_MIN}",
                context={**ctx, "score_components": score.score_components},
                symbol=DEFAULT_SYMBOL,
            )
        return None, {**ctx, "reject_reason": "QUALITY_LOW"}

    if score.tier == "watchlist":
        if log_rejections:
            log_rejection_event(
                stage="QUALITY",
                direction="BUY" if direction > 0 else "SELL",
                reason=f"watchlist score={score.quality_score}",
                context={**ctx, "score_components": score.score_components},
                symbol=DEFAULT_SYMBOL,
            )
        return None, {**ctx, "reject_reason": "WATCHLIST"}

    return score, ctx
