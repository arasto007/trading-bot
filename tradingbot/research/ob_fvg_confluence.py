"""PHASE 16B — OB + FVG Institutional Confluence (research only).

Institutional OB validity:
  1) Displacement within 3 bars after OB
  2) Displacement creates measurable FVG
  3) FVG overlaps OB by >= 20%
  4) Sweep occurs before displacement
  5) BOS happens after displacement (not before)

Score 0-100:
  ob_strength 25 | fvg_quality 25 | overlap_quality 20
  | displacement_confirmation 20 | sweep_context 10

NO live / router / execution changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.domain.price_action import (
    FairValueGap,
    OrderBlock,
    StructureBreak,
    SwingPoint,
    _liquidity_sweep,
    )


@dataclass
class ConfluenceScore:
    ob_strength: float
    fvg_quality: float
    overlap_quality: float
    displacement_confirmation: float
    sweep_context: float
    valid: bool
    overlap_pct: float
    ob_index: int | None
    disp_index: int | None
    fvg_index: int | None
    bos_index: int | None
    sweep_index: int | None

    @property
    def total(self) -> float:
        return round(
            self.ob_strength
            + self.fvg_quality
            + self.overlap_quality
            + self.displacement_confirmation
            + self.sweep_context,
            2,
        )


def _atr(df: pd.DataFrame, i: int) -> float:
    if "atr" in df.columns and not pd.isna(df["atr"].iloc[i]):
        v = float(df["atr"].iloc[i])
        if v > 0:
            return v
    return max(float(df["high"].iloc[i]) - float(df["low"].iloc[i]), 1e-9)


def _body_atr(df: pd.DataFrame, i: int) -> float:
    atr = _atr(df, i)
    o = float(df["open"].iloc[i])
    c = float(df["close"].iloc[i])
    return abs(c - o) / atr


def _is_displacement(df: pd.DataFrame, i: int, direction: int, *, min_body_atr: float = 0.45) -> bool:
    o = float(df["open"].iloc[i])
    c = float(df["close"].iloc[i])
    if direction > 0 and c <= o:
        return False
    if direction < 0 and c >= o:
        return False
    return _body_atr(df, i) >= min_body_atr


def _fvg_at(df: pd.DataFrame, i: int, direction: int) -> FairValueGap | None:
    """3-candle FVG completed at bar i (gap between i-2 and i)."""
    if i < 2:
        return None
    h2, l2 = float(df["high"].iloc[i - 2]), float(df["low"].iloc[i - 2])
    h0, l0 = float(df["high"].iloc[i]), float(df["low"].iloc[i])
    if direction > 0 and l0 > h2:
        return FairValueGap(i, float(l0), float(h2), 1)
    if direction < 0 and h0 < l2:
        return FairValueGap(i, float(l2), float(h0), -1)
    return None


def _overlap_pct(ob: OrderBlock, gap: FairValueGap) -> float:
    lo = max(ob.bottom, gap.bottom)
    hi = min(ob.top, gap.top)
    if hi <= lo:
        return 0.0
    ob_size = max(ob.top - ob.bottom, 1e-9)
    return float((hi - lo) / ob_size)


def _find_sweep_before(
    df: pd.DataFrame, swings: list[SwingPoint], disp_i: int, direction: int, lookback: int = 12
) -> int | None:
    start = max(0, disp_i - lookback)
    for j in range(disp_i - 1, start - 1, -1):
        sw = _liquidity_sweep(df, swings, j)
        if sw == direction:
            return j
    # asian-style wick sweep proxy: take opposite extreme then close back
    for j in range(disp_i - 1, start - 1, -1):
        row = df.iloc[j]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        rng = max(h - l, 1e-9)
        if direction > 0:
            # sweep lows: long lower wick, close in upper half
            if (min(o, c) - l) / rng >= 0.4 and c > (h + l) / 2:
                return j
        else:
            if (h - max(o, c)) / rng >= 0.4 and c < (h + l) / 2:
                return j
    return None


def _bos_after(
    breaks: list[StructureBreak], disp_i: int, setup_i: int, direction: int
) -> tuple[int | None, bool]:
    """Return (bos_index, had_bos_before_disp)."""
    bos_before = False
    bos_after_idx = None
    for br in breaks:
        if br.kind != "bos" or br.direction != direction:
            continue
        if br.index < disp_i:
            bos_before = True
        if disp_i < br.index <= setup_i:
            if bos_after_idx is None or br.index < bos_after_idx:
                bos_after_idx = br.index
    return bos_after_idx, bos_before


def _loose_ob_hit(df: pd.DataFrame, i: int, direction: int, price: float) -> bool:
    """Current loose OB logic: any matching OB containing/near price."""
    obs: list[OrderBlock] = df.attrs.get("pa_obs", []) or []
    atr = _atr(df, i)
    for ob in reversed(obs):
        if ob.direction != direction:
            continue
        if ob.index > i or ob.index < i - 40:
            continue
        if ob.bottom <= price <= ob.top:
            return True
        if abs(price - ob.top) <= atr * 0.25 or abs(price - ob.bottom) <= atr * 0.25:
            return True
    return False


def evaluate_institutional_confluence(
    df: pd.DataFrame,
    i: int,
    *,
    direction: int,
    price: float | None = None,
) -> ConfluenceScore:
    """Find best institutional OB+FVG confluence ending at/near bar i."""
    empty = ConfluenceScore(
        0, 0, 0, 0, 0, False, 0.0, None, None, None, None, None
    )
    obs: list[OrderBlock] = list(df.attrs.get("pa_obs", []) or [])
    breaks: list[StructureBreak] = list(df.attrs.get("pa_breaks", []) or [])
    swings: list[SwingPoint] = list(df.attrs.get("pa_swings", []) or [])
    if price is None:
        price = float(df["close"].iloc[i])

    # Also consider last opposing candle as candidate OB (loose structure OB may miss)
    # Stick to attrs OBs primarily; augment with last impulse candle in direction
    candidates = [ob for ob in obs if ob.direction == direction and 0 <= ob.index < i]
    # recent candle OB candidates (last 15 bars)
    for j in range(max(0, i - 15), i):
        o = float(df["open"].iloc[j])
        c = float(df["close"].iloc[j])
        # opposing candle as OB base
        if direction > 0 and c < o:
            candidates.append(
                OrderBlock(j, float(df["high"].iloc[j]), float(df["low"].iloc[j]), 1)
            )
        if direction < 0 and c > o:
            candidates.append(
                OrderBlock(j, float(df["high"].iloc[j]), float(df["low"].iloc[j]), -1)
            )

    best: ConfluenceScore | None = None

    for ob in candidates:
        # displacement within 3 bars after OB
        disp_idx = None
        for k in range(ob.index + 1, min(len(df), ob.index + 1 + 3)):
            if _is_displacement(df, k, direction):
                disp_idx = k
                break
        if disp_idx is None:
            continue

        gap = _fvg_at(df, disp_idx, direction)
        if gap is None:
            # try next bar after displacement (gap completes on impulse)
            if disp_idx + 1 < len(df):
                gap = _fvg_at(df, min(disp_idx + 1, i), direction)
        if gap is None:
            continue

        ov = _overlap_pct(ob, gap)
        if ov < 0.20:
            continue

        sweep_i = _find_sweep_before(df, swings, disp_idx, direction)
        if sweep_i is None:
            continue

        bos_i, bos_before = _bos_after(breaks, disp_idx, i, direction)
        # Rule 5: BOS after displacement, not before
        if bos_before and bos_i is None:
            continue
        if bos_i is None:
            # allow BOS shortly after setup bar window if break list has later bos
            # still require bos after disp by setup time
            continue
        if bos_i <= disp_idx:
            continue

        # --- scoring ---
        atr = _atr(df, disp_idx)
        ob_size = (ob.top - ob.bottom) / atr
        # strength: size in ATR band 0.3-1.5 + freshness
        age = i - ob.index
        ob_strength = min(25.0, 10.0 + min(10.0, ob_size * 8.0) + max(0.0, 5.0 - age * 0.3))

        fvg_size = abs(gap.top - gap.bottom) / atr
        fvg_quality = min(25.0, 8.0 + min(12.0, fvg_size * 20.0) + (5.0 if gap.bottom <= price <= gap.top else 0.0))

        overlap_quality = min(20.0, (ov / 0.20) * 10.0 + min(10.0, (ov - 0.20) * 25.0))

        body = _body_atr(df, disp_idx)
        displacement_confirmation = min(20.0, body / 0.45 * 12.0 + (8.0 if disp_idx - ob.index <= 2 else 4.0))

        sweep_age = disp_idx - sweep_i
        sweep_context = min(10.0, 6.0 + max(0.0, 4.0 - sweep_age * 0.5))

        cand = ConfluenceScore(
            ob_strength=round(ob_strength, 2),
            fvg_quality=round(fvg_quality, 2),
            overlap_quality=round(overlap_quality, 2),
            displacement_confirmation=round(displacement_confirmation, 2),
            sweep_context=round(sweep_context, 2),
            valid=True,
            overlap_pct=round(ov, 4),
            ob_index=ob.index,
            disp_index=disp_idx,
            fvg_index=gap.index,
            bos_index=bos_i,
            sweep_index=sweep_i,
        )
        if best is None or cand.total > best.total:
            best = cand

    return best if best is not None else empty


def current_loose_ob_valid(df: pd.DataFrame, i: int, direction: int, price: float) -> bool:
    return _loose_ob_hit(df, i, direction, price)