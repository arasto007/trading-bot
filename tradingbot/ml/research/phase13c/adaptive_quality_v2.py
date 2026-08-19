"""
Phase 13C - Adaptive Quality v2 + ML confirmation (RESEARCH ONLY).

Dynamic weight budgets always sum to 100. ML adds points; never replaces direction.
Not wired to live routing or order execution.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.strategies.adaptive_quality_engine import (
    ATR_BAND,
    resolve_candidate_direction,
)
from tradingbot.strategies.adaptive_regime import (
    MIN_EMA_SEP,
    _bar_open_hour_utc,
    _ema_sep_ok,
    _h1_aligned,
    classify_regime,
)

ROOT = Path(__file__).resolve().parents[4]
PHASE11A_MODELS = ROOT / "data" / "ml" / "research" / "phase11a" / "models"

# Dynamic weight envelopes (points). Regime picks a row; rows sum to 100.
WEIGHT_MATRIX: dict[str, dict[str, int]] = {
    "TREND": {"h1": 35, "atr": 15, "ema": 20, "session": 10, "ml": 20},
    "EXPANSION": {"h1": 25, "atr": 25, "ema": 15, "session": 15, "ml": 20},
    "RANGING": {"h1": 20, "atr": 20, "ema": 25, "session": 15, "ml": 20},
    "HIGH_VOLATILITY": {"h1": 25, "atr": 25, "ema": 15, "session": 15, "ml": 20},
    "LOW_VOLATILITY": {"h1": 20, "atr": 20, "ema": 25, "session": 15, "ml": 20},
    "RANGE": {"h1": 20, "atr": 20, "ema": 25, "session": 15, "ml": 20},
    "DEFAULT": {"h1": 30, "atr": 20, "ema": 20, "session": 10, "ml": 20},
}

# Spec envelopes for reporting
WEIGHT_RANGES = {
    "h1": (20, 35),
    "atr": (15, 25),
    "ema": (15, 25),
    "session": (0, 15),
    "ml": (0, 20),
}

WATCHLIST_LO = 60
WATCHLIST_HI = 69


@dataclass(frozen=True)
class MlShadowView:
    probability: float
    expected_edge_r: float
    confidence_bucket: str  # low | medium | high
    regime: str
    model_name: str


@dataclass(frozen=True)
class HybridV2Result:
    quality_score: float
    score_components: dict[str, float]
    weight_budget: dict[str, int]
    tier: str  # reject | watchlist | tradeable
    direction: int | None
    ml: MlShadowView | None
    promoted_from_watchlist: bool = False
    promotion_reasons: tuple[str, ...] = field(default_factory=tuple)
    reject_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_score": round(float(self.quality_score), 2),
            "score_components": {k: round(float(v), 2) for k, v in self.score_components.items()},
            "weight_budget": dict(self.weight_budget),
            "tier": self.tier,
            "direction": self.direction,
            "ml": None
            if self.ml is None
            else {
                "probability": round(self.ml.probability, 4),
                "expected_edge_r": round(self.ml.expected_edge_r, 4),
                "confidence_bucket": self.ml.confidence_bucket,
                "regime": self.ml.regime,
                "model_name": self.ml.model_name,
            },
            "promoted_from_watchlist": self.promoted_from_watchlist,
            "promotion_reasons": list(self.promotion_reasons),
            "reject_reason": self.reject_reason,
        }


def load_phase11a_regime_models() -> dict[str, Any]:
    """Load Phase 11A TREND / EXPANSION / RANGING lightgbm shadow models."""
    mapping = {
        "TREND": PHASE11A_MODELS / "trend_lightgbm.pkl",
        "EXPANSION": PHASE11A_MODELS / "expansion_lightgbm.pkl",
        "RANGING": PHASE11A_MODELS / "ranging_lightgbm.pkl",
    }
    out: dict[str, Any] = {}
    for regime, path in mapping.items():
        if not path.is_file():
            continue
        art = pickle.loads(path.read_bytes())
        out[regime] = art
    return out


def _map_adaptive_regime_to_ml(regime: str) -> str:
    r = (regime or "").upper()
    if r in ("TREND", "STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        return "TREND"
    if r in ("HIGH_VOLATILITY", "EXPANSION", "VOLATILE"):
        return "EXPANSION"
    if r in ("RANGE", "RANGING", "LOW_VOLATILITY"):
        return "RANGING"
    return "TREND"


def weight_budget_for_regime(regime: str) -> dict[str, int]:
    key = (regime or "DEFAULT").upper()
    budget = dict(WEIGHT_MATRIX.get(key) or WEIGHT_MATRIX["DEFAULT"])
    # Enforce envelope clamps then renormalize to exactly 100
    for k, (lo, hi) in WEIGHT_RANGES.items():
        budget[k] = int(np.clip(budget.get(k, lo), lo, hi))
    total = sum(budget.values())
    if total != 100:
        # scale preserving integers as close as possible
        scaled = {k: max(WEIGHT_RANGES[k][0], int(round(v * 100 / total))) for k, v in budget.items()}
        drift = 100 - sum(scaled.values())
        # adjust ML bucket first
        scaled["ml"] = int(np.clip(scaled["ml"] + drift, WEIGHT_RANGES["ml"][0], WEIGHT_RANGES["ml"][1]))
        # final fix on h1 if still off
        drift = 100 - sum(scaled.values())
        scaled["h1"] = int(np.clip(scaled["h1"] + drift, WEIGHT_RANGES["h1"][0], WEIGHT_RANGES["h1"][1]))
        budget = scaled
    return budget


def _session_strength(ts: pd.Timestamp) -> float:
    hour = _bar_open_hour_utc(ts)
    if 12 <= hour < 17:
        return 1.0
    if 7 <= hour < 12:
        return 0.85
    if 17 <= hour < 21:
        return 0.55
    return 0.15


def _atr_strength(row: pd.Series, frame: pd.DataFrame, idx: int) -> float:
    atr_pct = float(row.get("atr_pct", np.nan))
    if not np.isfinite(atr_pct):
        return 0.0
    lo, hi = ATR_BAND
    if lo <= atr_pct <= hi:
        # center of band = 1.0
        mid = 0.5 * (lo + hi)
        half = 0.5 * (hi - lo)
        return float(np.clip(1.0 - abs(atr_pct - mid) / max(half, 1e-9) * 0.35, 0.55, 1.0))
    # soft credit outside band
    if 0.20 <= atr_pct < lo:
        return 0.35
    if hi < atr_pct <= 0.90:
        return 0.40
    return 0.10


def _ema_strength(row: pd.Series) -> float:
    if not _ema_sep_ok(row):
        ema20, ema50, close = float(row.get("ema20", np.nan)), float(row.get("ema50", np.nan)), float(row.get("close", np.nan))
        if not all(np.isfinite(x) for x in (ema20, ema50, close)) or close <= 0:
            return 0.0
        sep = abs(ema20 - ema50) / close
        return float(np.clip(sep / max(MIN_EMA_SEP, 1e-9), 0.0, 0.85))
    return 1.0


def _h1_strength(row: pd.Series, direction: int) -> float:
    h1 = float(row.get("h1_trend", 0) or 0)
    if direction > 0:
        if h1 > 0:
            return 1.0
        if h1 == 0:
            return 0.55
        return 0.15
    if h1 < 0:
        return 1.0
    if h1 == 0:
        return 0.55
    return 0.15


def confidence_bucket(prob: float) -> str:
    if prob >= 0.65:
        return "high"
    if prob >= 0.55:
        return "medium"
    return "low"


def expected_edge_r(prob: float, *, win_r: float = 1.6, loss_r: float = 1.0) -> float:
    """Simple expectancy proxy from win probability assuming +win_r / -loss_r."""
    p = float(np.clip(prob, 0.0, 1.0))
    return p * win_r - (1.0 - p) * loss_r


def score_ml_shadow(
    frame: pd.DataFrame,
    idx: int,
    models: dict[str, Any],
    *,
    adaptive_regime: str,
) -> MlShadowView:
    from tradingbot.ml.feature_store import InstitutionalFeatureStore, classify_regime
    from tradingbot.domain.market_filters import compute_adx

    feats = InstitutionalFeatureStore.compute_at(frame, idx, symbol="XAUUSD")
    adx = compute_adx(frame.iloc[: idx + 1])
    feat_regime = classify_regime(adx, float(feats.get("atr_pct", 50.0)))
    ml_regime = feat_regime if feat_regime in models else _map_adaptive_regime_to_ml(adaptive_regime)
    art = models.get(ml_regime)
    if art is None:
        for fb in ("TREND", "RANGING", "EXPANSION"):
            if fb in models:
                art = models[fb]
                ml_regime = fb
                break
    if art is None:
        return MlShadowView(0.5, 0.0, "low", ml_regime, "none")

    names = list(art.get("features") or [])
    x = np.array([[float(feats.get(f, 0.0)) for f in names]], dtype=float)
    try:
        prob = float(art["model"].predict_proba(x)[0, 1])
    except Exception:
        prob = 0.5
    return MlShadowView(
        probability=prob,
        expected_edge_r=expected_edge_r(prob),
        confidence_bucket=confidence_bucket(prob),
        regime=ml_regime,
        model_name=str(art.get("model_type") or type(art["model"]).__name__),
    )


def _ml_points(ml: MlShadowView, budget: int) -> float:
    """Map probability + edge into [0, budget] points - additive confirmation only."""
    if budget <= 0:
        return 0.0
    # Center at 0.5 -> 0 points; 0.70+ -> full budget when edge positive
    edge_factor = float(np.clip((ml.expected_edge_r + 0.2) / 0.8, 0.0, 1.0))
    prob_factor = float(np.clip((ml.probability - 0.45) / 0.30, 0.0, 1.0))
    strength = 0.55 * prob_factor + 0.45 * edge_factor
    if ml.confidence_bucket == "high":
        strength = min(1.0, strength + 0.08)
    elif ml.confidence_bucket == "low":
        strength *= 0.75
    return budget * strength


def compute_quality_v2(
    frame: pd.DataFrame,
    idx: int,
    direction: int,
    *,
    ml: MlShadowView | None,
    bar_open: pd.Timestamp | None = None,
) -> tuple[float, dict[str, float], dict[str, int], str]:
    row = frame.iloc[idx]
    ts = bar_open or pd.Timestamp(frame.index[idx])
    adaptive_regime = classify_regime(row)
    budget = weight_budget_for_regime(adaptive_regime)

    h1_pts = budget["h1"] * _h1_strength(row, direction)
    atr_pts = budget["atr"] * _atr_strength(row, frame, idx)
    ema_pts = budget["ema"] * _ema_strength(row)
    session_pts = budget["session"] * _session_strength(ts)
    ml_pts = _ml_points(ml, budget["ml"]) if ml is not None else 0.0

    components = {
        "h1": float(h1_pts),
        "atr": float(atr_pts),
        "ema": float(ema_pts),
        "session": float(session_pts),
        "ml": float(ml_pts),
    }
    total = float(sum(components.values()))
    return total, components, budget, adaptive_regime


def _rolling_spread_median(frame: pd.DataFrame, idx: int, window: int = 48) -> float:
    """Proxy spread from bar range when true spread unavailable."""
    start = max(0, idx - window + 1)
    ranges = (frame["high"].iloc[start : idx + 1] - frame["low"].iloc[start : idx + 1]).astype(float)
    med = float(ranges.median()) if len(ranges) else 0.0
    return med


def _bar_spread_proxy(row: pd.Series) -> float:
    return float(row["high"] - row["low"])


def _atr_stable_or_expanding(frame: pd.DataFrame, idx: int) -> bool:
    if idx < 6:
        return False
    col = "atr" if "atr" in frame.columns else None
    if col is None and "atr_pct" in frame.columns:
        series = frame["atr_pct"].astype(float)
    elif col:
        series = frame[col].astype(float)
    else:
        series = (frame["high"] - frame["low"]).astype(float)
    cur = float(series.iloc[idx])
    prev = float(series.iloc[idx - 3 : idx].mean())
    if not np.isfinite(cur) or not np.isfinite(prev) or prev <= 0:
        return False
    return cur >= prev * 0.95  # stable or expanding


def _opposite_h1_spike(frame: pd.DataFrame, idx: int, direction: int) -> bool:
    """True if H1 momentum flips hard against the setup."""
    row = frame.iloc[idx]
    h1 = float(row.get("h1_trend", 0) or 0)
    if direction > 0 and h1 < 0:
        return True
    if direction < 0 and h1 > 0:
        return True
    # spike: large adverse close move vs prior bar while h1 weakly opposed
    if idx < 1:
        return False
    prev = frame.iloc[idx - 1]
    move = float(row["close"] - prev["close"])
    atr = float(row.get("atr", abs(row["high"] - row["low"])) or 1.0)
    if atr <= 0:
        return False
    if direction > 0 and move < -0.6 * atr:
        return True
    if direction < 0 and move > 0.6 * atr:
        return True
    return False


def try_watchlist_promotion(
    frame: pd.DataFrame,
    idx: int,
    direction: int,
    quality_score: float,
) -> tuple[bool, tuple[str, ...]]:
    """Promote scores 60-69 when next-bar confirms and microstructure filters pass."""
    if not (WATCHLIST_LO <= quality_score <= WATCHLIST_HI):
        return False, ()
    if idx + 1 >= len(frame):
        return False, ("no_next_bar",)

    reasons: list[str] = []
    nxt = frame.iloc[idx + 1]
    cur_close = float(frame.iloc[idx]["close"])
    nxt_close = float(nxt["close"])
    confirms = (direction > 0 and nxt_close > cur_close) or (direction < 0 and nxt_close < cur_close)
    if not confirms:
        return False, ("next_bar_not_confirm",)
    reasons.append("next_bar_confirm")

    spread = _bar_spread_proxy(frame.iloc[idx])
    med = _rolling_spread_median(frame, idx)
    if med <= 0 or spread >= med:
        return False, ("spread_not_below_median",)
    reasons.append("spread_lt_median")

    if not _atr_stable_or_expanding(frame, idx):
        return False, ("atr_not_stable_expanding",)
    reasons.append("atr_stable_or_expanding")

    if _opposite_h1_spike(frame, idx, direction):
        return False, ("opposite_h1_momentum_spike",)
    reasons.append("no_opposite_h1_spike")

    return True, tuple(reasons)


def evaluate_hybrid_v2_at_index(
    frame: pd.DataFrame,
    idx: int,
    models: dict[str, Any],
    *,
    threshold: float = 70.0,
    allow_watchlist_promotion: bool = True,
    include_ml: bool = True,
) -> HybridV2Result:
    if idx < 0 or idx >= len(frame):
        return HybridV2Result(0.0, {}, WEIGHT_MATRIX["DEFAULT"], "reject", None, None, reject_reason="bad_index")

    row = frame.iloc[idx]
    adaptive_regime = classify_regime(row)
    if adaptive_regime == "NO_TRADE":
        return HybridV2Result(0.0, {}, weight_budget_for_regime(adaptive_regime), "reject", None, None, reject_reason="NO_TRADE")

    direction = resolve_candidate_direction(frame, idx)
    if direction is None:
        return HybridV2Result(0.0, {}, weight_budget_for_regime(adaptive_regime), "reject", None, None, reject_reason="NO_DIRECTION")

    ml = score_ml_shadow(frame, idx, models, adaptive_regime=adaptive_regime) if include_ml else None
    # When ML disabled for ablation, zero its budget into other legs proportionally? keep budget but 0 pts
    total, components, budget, _ = compute_quality_v2(
        frame, idx, direction, ml=ml, bar_open=pd.Timestamp(frame.index[idx])
    )

    promoted = False
    promo_reasons: tuple[str, ...] = ()
    if total >= threshold:
        tier = "tradeable"
    elif allow_watchlist_promotion and WATCHLIST_LO <= total <= WATCHLIST_HI:
        ok, promo_reasons = try_watchlist_promotion(frame, idx, direction, total)
        if ok:
            tier = "tradeable"
            promoted = True
        else:
            tier = "watchlist"
    elif total >= WATCHLIST_LO:
        tier = "watchlist"
    else:
        tier = "reject"

    return HybridV2Result(
        quality_score=total,
        score_components=components,
        weight_budget=budget,
        tier=tier,
        direction=direction,
        ml=ml,
        promoted_from_watchlist=promoted,
        promotion_reasons=promo_reasons,
        reject_reason="" if tier == "tradeable" else tier.upper(),
    )
