"""Phase 12C — Adaptive Quality + ML hybrid decision layer (RESEARCH ONLY).

Combines rule-based quality scoring with regime-specific ML confirmation.
Not wired to live execution — use via scripts/phase12c_hybrid_certification.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.strategies.adaptive_quality_engine import (
    QualityScoreResult,
    compute_quality_score,
    resolve_candidate_direction,
)

# Hybrid thresholds (Phase 12C spec)
QUALITY_REJECT_MAX = 65
QUALITY_ML_STRICT_MIN = 65
QUALITY_ML_STRICT_MAX = 75
ML_THRESHOLD_STRICT = 0.65
ML_THRESHOLD_RELAXED = 0.55
SESSION_QUALITY_MIN = 0.6
SPREAD_QUALITY_MIN = 0.5


@dataclass(frozen=True)
class HybridDecision:
    accepted: bool
    quality_score: int
    ml_probability: float
    session_quality: float
    spread_quality: float
    h1_trend: float
    direction: int
    reject_reason: str
    ml_threshold_used: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "quality_score": self.quality_score,
            "ml_probability": round(self.ml_probability, 4),
            "session_quality": round(self.session_quality, 4),
            "spread_quality": round(self.spread_quality, 4),
            "h1_trend": round(self.h1_trend, 4),
            "direction": self.direction,
            "reject_reason": self.reject_reason,
            "ml_threshold_used": self.ml_threshold_used,
        }


def session_quality(ts: pd.Timestamp) -> float:
    """0–1 session favourability (London/overlap weighted)."""
    hour = ts.hour if hasattr(ts, "hour") else pd.Timestamp(ts).hour
    if 12 <= hour < 17:
        return 1.0
    if 7 <= hour < 12:
        return 0.85
    if 17 <= hour < 21:
        return 0.65
    if 0 <= hour < 7:
        return 0.35
    return 0.2


def spread_quality(spread_pips: float, *, ref_pips: float = 4.0, max_pips: float = 12.0) -> float:
    """1.0 = tight spread; decays as spread widens."""
    if spread_pips <= 0:
        return 0.7
    if spread_pips <= ref_pips:
        return 1.0
    excess = (spread_pips - ref_pips) / max(max_pips - ref_pips, 1e-9)
    return float(np.clip(1.0 - excess, 0.0, 1.0))


def h1_not_opposite(h1_trend: float, direction: int) -> bool:
    """H1 trend must not oppose trade direction."""
    if h1_trend == 0:
        return True
    if direction > 0:
        return h1_trend >= 0
    return h1_trend <= 0


def required_ml_threshold(quality_score: int) -> float | None:
    if quality_score < QUALITY_REJECT_MAX:
        return None
    if quality_score < QUALITY_ML_STRICT_MAX:
        return ML_THRESHOLD_STRICT
    return ML_THRESHOLD_RELAXED


def evaluate_hybrid_decision(
    frame: pd.DataFrame,
    idx: int,
    *,
    ml_probability: float,
    spread_pips: float = 4.0,
    h1_trend: float | None = None,
    quality_result: QualityScoreResult | None = None,
    direction: int | None = None,
) -> HybridDecision:
    """
    Hybrid gate: quality tiers + ML confirmation + session/spread/H1 filters.

    Returns HybridDecision with accepted=True only when all gates pass.
    """
    if idx < 0 or idx >= len(frame):
        return HybridDecision(
            accepted=False,
            quality_score=0,
            ml_probability=ml_probability,
            session_quality=0.0,
            spread_quality=0.0,
            h1_trend=0.0,
            direction=0,
            reject_reason="invalid_index",
            ml_threshold_used=0.0,
        )

    ts = pd.Timestamp(frame.index[idx])
    dir_candidate = direction
    if dir_candidate is None:
        dir_candidate = resolve_candidate_direction(frame, idx)
    if dir_candidate is None:
        return HybridDecision(
            accepted=False,
            quality_score=0,
            ml_probability=ml_probability,
            session_quality=session_quality(ts),
            spread_quality=spread_quality(spread_pips),
            h1_trend=float(h1_trend or 0.0),
            direction=0,
            reject_reason="no_direction",
            ml_threshold_used=0.0,
        )

    score = quality_result or compute_quality_score(frame, idx, dir_candidate, bar_open=ts)
    sq = session_quality(ts)
    spq = spread_quality(spread_pips)

    if h1_trend is None:
        try:
            from tradingbot.ml.feature_store import InstitutionalFeatureStore

            feats = InstitutionalFeatureStore.compute_at(frame, idx, symbol="XAUUSD")
            h1_val = float(feats.get("h1_trend", 0.0))
        except Exception:
            h1_val = 0.0
    else:
        h1_val = float(h1_trend)

    if score.quality_score < QUALITY_REJECT_MAX:
        return HybridDecision(
            accepted=False,
            quality_score=score.quality_score,
            ml_probability=ml_probability,
            session_quality=sq,
            spread_quality=spq,
            h1_trend=h1_val,
            direction=dir_candidate,
            reject_reason=f"quality<{QUALITY_REJECT_MAX}",
            ml_threshold_used=0.0,
        )

    if sq < SESSION_QUALITY_MIN:
        return HybridDecision(
            accepted=False,
            quality_score=score.quality_score,
            ml_probability=ml_probability,
            session_quality=sq,
            spread_quality=spq,
            h1_trend=h1_val,
            direction=dir_candidate,
            reject_reason="session_quality_low",
            ml_threshold_used=0.0,
        )

    if spq < SPREAD_QUALITY_MIN:
        return HybridDecision(
            accepted=False,
            quality_score=score.quality_score,
            ml_probability=ml_probability,
            session_quality=sq,
            spread_quality=spq,
            h1_trend=h1_val,
            direction=dir_candidate,
            reject_reason="spread_quality_low",
            ml_threshold_used=0.0,
        )

    if not h1_not_opposite(h1_val, dir_candidate):
        return HybridDecision(
            accepted=False,
            quality_score=score.quality_score,
            ml_probability=ml_probability,
            session_quality=sq,
            spread_quality=spq,
            h1_trend=h1_val,
            direction=dir_candidate,
            reject_reason="h1_opposite",
            ml_threshold_used=0.0,
        )

    ml_th = required_ml_threshold(score.quality_score)
    if ml_th is None:
        return HybridDecision(
            accepted=False,
            quality_score=score.quality_score,
            ml_probability=ml_probability,
            session_quality=sq,
            spread_quality=spq,
            h1_trend=h1_val,
            direction=dir_candidate,
            reject_reason="quality_reject",
            ml_threshold_used=0.0,
        )

    if ml_probability < ml_th:
        return HybridDecision(
            accepted=False,
            quality_score=score.quality_score,
            ml_probability=ml_probability,
            session_quality=sq,
            spread_quality=spq,
            h1_trend=h1_val,
            direction=dir_candidate,
            reject_reason=f"ml<{ml_th}",
            ml_threshold_used=ml_th,
        )

    return HybridDecision(
        accepted=True,
        quality_score=score.quality_score,
        ml_probability=ml_probability,
        session_quality=sq,
        spread_quality=spq,
        h1_trend=h1_val,
        direction=dir_candidate,
        reject_reason="accepted",
        ml_threshold_used=ml_th,
    )
