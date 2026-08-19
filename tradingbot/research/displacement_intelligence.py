"""PHASE 16A — Institutional Displacement Intelligence (research only).

Normalized displacement features + weighted score 0-100 for PA setups.
NO live / router / execution / config changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

BUCKETS = (
    (50, 60, "50-60"),
    (60, 70, "60-70"),
    (70, 80, "70-80"),
    (80, 90, "80-90"),
    (90, 101, "90-100"),
)

# Soft caps for mapping feature -> weight points
CAP_BODY_ATR = 1.0
CAP_RANGE_EXP = 2.0
CAP_FVG_ATR = 0.50
CAP_FOLLOW_ATR = 1.0


@dataclass
class DisplacementFeatures:
    body_atr: float
    close_near_high: float
    close_near_low: float
    range_expansion: float
    fvg_size_atr: float
    follow_through_2: float
    displacement_velocity: float
    close_near_extreme: float


@dataclass
class DisplacementScore:
    features: DisplacementFeatures
    body_atr_pts: float
    range_expansion_pts: float
    close_near_extreme_pts: float
    fvg_size_atr_pts: float
    follow_through_2_pts: float

    @property
    def total(self) -> float:
        return round(
            self.body_atr_pts
            + self.range_expansion_pts
            + self.close_near_extreme_pts
            + self.fvg_size_atr_pts
            + self.follow_through_2_pts,
            2,
        )


def _atr14(df: pd.DataFrame, i: int) -> float:
    if "atr" in df.columns and not pd.isna(df["atr"].iloc[i]):
        v = float(df["atr"].iloc[i])
        if v > 0:
            return v
    # fallback TR rolling
    start = max(0, i - 13)
    trs = []
    for j in range(start, i + 1):
        h = float(df["high"].iloc[j])
        l = float(df["low"].iloc[j])
        if j == 0:
            trs.append(h - l)
        else:
            pc = float(df["close"].iloc[j - 1])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return max(float(np.mean(trs)) if trs else 1e-9, 1e-9)


def _bar_range(df: pd.DataFrame, i: int) -> float:
    return max(float(df["high"].iloc[i]) - float(df["low"].iloc[i]), 1e-9)


def _fvg_size_atr(df: pd.DataFrame, i: int, direction: int, atr: float) -> float:
    """Largest recent directional FVG size / ATR (from attrs or local detect)."""
    fvgs = df.attrs.get("pa_fvgs", []) or []
    best = 0.0
    for gap in reversed(fvgs):
        if gap.direction != direction:
            continue
        if gap.index > i or gap.index < i - 40:
            continue
        size = abs(float(gap.top) - float(gap.bottom))
        best = max(best, size / atr)
        break  # most recent matching
    if best > 0:
        return float(best)
    # local 3-candle FVG at i
    if i < 2:
        return 0.0
    h2, l2 = float(df["high"].iloc[i - 2]), float(df["low"].iloc[i - 2])
    h0, l0 = float(df["high"].iloc[i]), float(df["low"].iloc[i])
    if direction > 0 and l0 > h2:
        return float((l0 - h2) / atr)
    if direction < 0 and h0 < l2:
        return float((l2 - h0) / atr)
    return 0.0


def _follow_through_2(df: pd.DataFrame, i: int, direction: int, atr: float) -> float:
    """Max favorable excursion over next 2 bars / ATR."""
    entry = float(df["close"].iloc[i])
    end = min(len(df), i + 1 + 2)
    mfe = 0.0
    for j in range(i + 1, end):
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
        if direction > 0:
            mfe = max(mfe, max(0.0, hi - entry))
        else:
            mfe = max(mfe, max(0.0, entry - lo))
    return float(mfe / atr)


def compute_displacement_features(
    df: pd.DataFrame, i: int, *, direction: int
) -> DisplacementFeatures:
    atr = _atr14(df, i)
    row = df.iloc[i]
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    rng = max(h - l, 1e-9)
    body_atr = abs(c - o) / atr
    close_near_high = (h - c) / rng
    close_near_low = (c - l) / rng

    # median of last 20 completed ranges (exclude current or include? use prior 20)
    ranges = [_bar_range(df, j) for j in range(max(0, i - 20), i)]
    med = float(np.median(ranges)) if ranges else rng
    med = max(med, 1e-9)
    range_expansion = rng / med

    fvg_size_atr = _fvg_size_atr(df, i, direction, atr)
    follow_through_2 = _follow_through_2(df, i, direction, atr)
    displacement_velocity = body_atr * range_expansion

    if direction > 0:
        close_near_extreme = float(np.clip(1.0 - close_near_high, 0.0, 1.0))
    else:
        close_near_extreme = float(np.clip(1.0 - close_near_low, 0.0, 1.0))

    return DisplacementFeatures(
        body_atr=round(body_atr, 6),
        close_near_high=round(close_near_high, 6),
        close_near_low=round(close_near_low, 6),
        range_expansion=round(range_expansion, 6),
        fvg_size_atr=round(fvg_size_atr, 6),
        follow_through_2=round(follow_through_2, 6),
        displacement_velocity=round(displacement_velocity, 6),
        close_near_extreme=round(close_near_extreme, 6),
    )


def _clamp01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def score_displacement(feats: DisplacementFeatures) -> DisplacementScore:
    """Weighted institutional displacement score 0-100."""
    body_pts = 25.0 * _clamp01(feats.body_atr / CAP_BODY_ATR)
    range_pts = 25.0 * _clamp01(feats.range_expansion / CAP_RANGE_EXP)
    extreme_pts = 15.0 * _clamp01(feats.close_near_extreme)
    fvg_pts = 20.0 * _clamp01(feats.fvg_size_atr / CAP_FVG_ATR)
    follow_pts = 15.0 * _clamp01(feats.follow_through_2 / CAP_FOLLOW_ATR)
    return DisplacementScore(
        features=feats,
        body_atr_pts=round(body_pts, 2),
        range_expansion_pts=round(range_pts, 2),
        close_near_extreme_pts=round(extreme_pts, 2),
        fvg_size_atr_pts=round(fvg_pts, 2),
        follow_through_2_pts=round(follow_pts, 2),
    )


def compute_displacement_score(
    df: pd.DataFrame, i: int, *, direction: int
) -> DisplacementScore:
    return score_displacement(compute_displacement_features(df, i, direction=direction))


def bucket_label(score: float) -> str | None:
    for lo, hi, name in BUCKETS:
        if lo <= score < hi:
            return name
    return None


def path_mfe_mae_final(
    df: pd.DataFrame,
    i: int,
    *,
    direction: int,
    entry: float,
    sl: float,
    tp: float,
    max_bars: int = 96,
) -> tuple[float, float, float]:
    risk = abs(entry - sl)
    if risk <= 0 or i >= len(df) - 1:
        return 0.0, 0.0, 0.0
    end = min(len(df), i + 1 + max_bars)
    mfe = mae = 0.0
    for j in range(i + 1, end):
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
        if direction > 0:
            mfe = max(mfe, max(0.0, (hi - entry) / risk))
            mae = max(mae, max(0.0, (entry - lo) / risk))
            if lo <= sl:
                return round(mfe, 4), round(mae, 4), round((sl - entry) / risk, 4)
            if hi >= tp:
                return round(mfe, 4), round(mae, 4), round((tp - entry) / risk, 4)
        else:
            mfe = max(mfe, max(0.0, (entry - lo) / risk))
            mae = max(mae, max(0.0, (hi - entry) / risk))
            if hi >= sl:
                return round(mfe, 4), round(mae, 4), round((entry - sl) / risk, 4)
            if lo <= tp:
                return round(mfe, 4), round(mae, 4), round((entry - tp) / risk, 4)
    close = float(df["close"].iloc[end - 1])
    final_r = ((close - entry) if direction > 0 else (entry - close)) / risk
    return round(mfe, 4), round(mae, 4), round(final_r, 4)


def metrics_from_trades(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_R": 0.0,
            "max_drawdown_R": 0.0,
            "mean_MFE_R": 0.0,
            "mean_MAE_R": 0.0,
        }
    rs = [float(r["final_R"]) for r in rows]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(rows),
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
        "profit_factor": round(pf, 3) if pf < 999 else 999.0,
        "expectancy_R": round(sum(rs) / len(rs), 4),
        "max_drawdown_R": round(mdd, 3),
        "mean_MFE_R": round(float(np.mean([float(r["MFE_R"]) for r in rows])), 4),
        "mean_MAE_R": round(float(np.mean([float(r["MAE_R"]) for r in rows])), 4),
    }