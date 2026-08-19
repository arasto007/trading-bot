"""
Price Action / SMC domain — market structure, liquidity, OB, FVG.

الگوبرداری از پیاده‌سازی‌های حرفه‌ای (BOS/CHoCH, sweep, OB retest, FVG fill).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class Trend(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"


class SetupType(str, Enum):
    LIQUIDITY_SWEEP = "liquidity_sweep"
    BOS_OB = "bos_ob"
    FVG_FILL = "fvg_fill"


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # high | low


@dataclass
class StructureBreak:
    index: int
    level: float
    kind: str  # bos | choch
    direction: int  # 1 bull, -1 bear


@dataclass
class OrderBlock:
    index: int
    top: float
    bottom: float
    direction: int


@dataclass
class FairValueGap:
    index: int
    top: float
    bottom: float
    direction: int
    filled: bool = False


@dataclass
class PriceActionSetup:
    direction: int
    setup: SetupType
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    confluence: float
    metadata: dict[str, Any]


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def find_swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[SwingPoint]:
    swings: list[SwingPoint] = []
    highs, lows = df["high"].values, df["low"].values
    n = len(df)
    for i in range(left, n - right):
        win_h = highs[i - left : i + right + 1]
        win_l = lows[i - left : i + right + 1]
        if highs[i] == win_h.max():
            swings.append(SwingPoint(i, float(highs[i]), "high"))
        elif lows[i] == win_l.min():
            swings.append(SwingPoint(i, float(lows[i]), "low"))
    return swings


def infer_trend(swings: list[SwingPoint]) -> Trend:
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return Trend.RANGE
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        return Trend.BULL
    if lh and ll:
        return Trend.BEAR
    return Trend.RANGE


def detect_structure_breaks(
    df: pd.DataFrame, swings: list[SwingPoint], *, close_break: bool = True, at_index: int | None = None
) -> list[StructureBreak]:
    """فقط شکست‌های اخیر — سریع برای بک‌تست کندل‌به‌کندل."""
    breaks: list[StructureBreak] = []
    trend = infer_trend(swings)
    end = len(df) if at_index is None else min(at_index + 1, len(df))
    start = max(1, end - 120)
    for i in range(start, end):
        c = df["close"].iloc[i]
        h, l = df["high"].iloc[i], df["low"].iloc[i]
        for sp in reversed(swings):
            if sp.index >= i or sp.index < i - 80:
                continue
            if sp.kind == "high":
                hit = c > sp.price if close_break else h > sp.price
                if hit:
                    kind = "bos" if trend == Trend.BULL else "choch"
                    breaks.append(StructureBreak(i, sp.price, kind, 1))
                    break
            else:
                hit = c < sp.price if close_break else l < sp.price
                if hit:
                    kind = "bos" if trend == Trend.BEAR else "choch"
                    breaks.append(StructureBreak(i, sp.price, kind, -1))
                    break
    return breaks


def detect_fvgs(df: pd.DataFrame, lookback: int = 80) -> list[FairValueGap]:
    gaps: list[FairValueGap] = []
    start = max(2, len(df) - lookback)
    for i in range(start, len(df)):
        h2, l2 = df["high"].iloc[i - 2], df["low"].iloc[i - 2]
        h0, l0 = df["high"].iloc[i], df["low"].iloc[i]
        if l0 > h2:
            gaps.append(FairValueGap(i, float(l0), float(h2), 1))
        elif h0 < l2:
            gaps.append(FairValueGap(i, float(l2), float(h0), -1))
    return gaps


def detect_order_blocks(
    df: pd.DataFrame, breaks: list[StructureBreak], lookback: int = 30
) -> list[OrderBlock]:
    obs: list[OrderBlock] = []
    for br in breaks[-lookback:]:
        idx = br.index
        if idx < 2:
            continue
        if br.direction == 1:
            ob_idx = idx - 1
            while ob_idx > 0 and df["close"].iloc[ob_idx] >= df["open"].iloc[ob_idx]:
                ob_idx -= 1
            if ob_idx <= 0:
                continue
            obs.append(
                OrderBlock(
                    ob_idx,
                    float(df["high"].iloc[ob_idx]),
                    float(df["low"].iloc[ob_idx]),
                    1,
                )
            )
        else:
            ob_idx = idx - 1
            while ob_idx > 0 and df["close"].iloc[ob_idx] <= df["open"].iloc[ob_idx]:
                ob_idx -= 1
            if ob_idx <= 0:
                continue
            obs.append(
                OrderBlock(
                    ob_idx,
                    float(df["high"].iloc[ob_idx]),
                    float(df["low"].iloc[ob_idx]),
                    -1,
                )
            )
    return obs


def _liquidity_sweep(
    df: pd.DataFrame, swings: list[SwingPoint], i: int, *, wick_pct: float = 0.0003
) -> int | None:
    """Return 1 if bullish sweep (took lows, closed above), -1 if bearish."""
    row = df.iloc[i]
    c, h, l = float(row["close"]), float(row["high"]), float(row["low"])
    recent_highs = [s for s in swings if s.kind == "high" and s.index < i][-3:]
    recent_lows = [s for s in swings if s.kind == "low" and s.index < i][-3:]
    for sp in recent_lows:
        if l < sp.price * (1 - wick_pct) and c > sp.price:
            return 1
    for sp in recent_highs:
        if h > sp.price * (1 + wick_pct) and c < sp.price:
            return -1
    return None


def _pin_bar(row: pd.Series, direction: int) -> bool:
    body = abs(row["close"] - row["open"])
    rng = max(row["high"] - row["low"], 1e-9)
    upper = row["high"] - max(row["open"], row["close"])
    lower = min(row["open"], row["close"]) - row["low"]
    if direction == 1:
        return lower / rng >= 0.55 and body / rng <= 0.35
    return upper / rng >= 0.55 and body / rng <= 0.35


def price_zone(df: pd.DataFrame, i: int, *, lookback: int = 50) -> str:
    """discount | equilibrium | premium نسبت به range اخیر."""
    start = max(0, i - lookback)
    window = df.iloc[start : i + 1]
    if window.empty:
        return "equilibrium"
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    if hi <= lo:
        return "equilibrium"
    mid = (hi + lo) / 2.0
    price = float(df["close"].iloc[i])
    band = (hi - lo) * 0.05
    if price < mid - band:
        return "discount"
    if price > mid + band:
        return "premium"
    return "equilibrium"


def had_recent_sweep(df: pd.DataFrame, swings: list[SwingPoint], i: int, *, bars: int = 12) -> bool:
    start = max(0, i - bars)
    for j in range(start, i + 1):
        if _liquidity_sweep(df, swings, j) is not None:
            return True
    return False


def zone_allows_direction(zone: str, direction: int) -> bool:
    if direction == 1:
        return zone in ("discount", "equilibrium")
    if direction == -1:
        return zone in ("premium", "equilibrium")
    return False


def _engulfing(df: pd.DataFrame, i: int) -> int | None:
    if i < 1:
        return None
    cur, prev = df.iloc[i], df.iloc[i - 1]
    if (
        prev["close"] < prev["open"]
        and cur["close"] > cur["open"]
        and cur["close"] > prev["open"]
        and cur["open"] < prev["close"]
    ):
        return 1
    if (
        prev["close"] > prev["open"]
        and cur["close"] < cur["open"]
        and cur["close"] < prev["open"]
        and cur["open"] > prev["close"]
    ):
        return -1
    return None


def enrich_price_action(
    df: pd.DataFrame, cfg: dict[str, Any], *, at_index: int | None = None
) -> pd.DataFrame:
    out = df.copy()
    out["atr"] = _atr(out, int(cfg.get("ATR_PERIOD", 14)))
    left = int(cfg.get("SWING_LEFT", 3))
    right = int(cfg.get("SWING_RIGHT", 3))
    tail_start = max(0, (at_index or len(out)) - 250)
    work = out.iloc[tail_start:]
    swings = find_swings(work, left, right)
    # adjust swing indices to full frame
    swings = [SwingPoint(s.index + tail_start, s.price, s.kind) for s in swings]
    idx = at_index if at_index is not None else len(out) - 1
    breaks = detect_structure_breaks(out, swings, at_index=idx)
    out.attrs["pa_swings"] = swings
    out.attrs["pa_breaks"] = breaks
    out.attrs["pa_fvgs"] = detect_fvgs(out, int(cfg.get("FVG_LOOKBACK", 80)))
    out.attrs["pa_obs"] = detect_order_blocks(out, breaks)
    out.attrs["pa_trend"] = infer_trend(swings)
    return out


def evaluate_setup_at(
    df: pd.DataFrame, i: int, cfg: dict[str, Any]
) -> PriceActionSetup | None:
    if i < 30 or i >= len(df):
        return None

    if bool(cfg.get("USE_REGIME_FILTER", False)):
        from tradingbot.domain.risk_logic import infer_regime_from_ohlcv, regime_blocks_entry

        regime = infer_regime_from_ohlcv(df, i)
        if regime_blocks_entry(regime):
            return None

    swings: list[SwingPoint] = df.attrs.get("pa_swings", [])
    breaks: list[StructureBreak] = df.attrs.get("pa_breaks", [])
    fvgs: list[FairValueGap] = df.attrs.get("pa_fvgs", [])
    obs: list[OrderBlock] = df.attrs.get("pa_obs", [])
    trend: Trend = df.attrs.get("pa_trend", Trend.RANGE)

    row = df.iloc[i]
    price = float(row["close"])
    atr = float(row["atr"]) if not pd.isna(row.get("atr")) else price * 0.001
    if atr <= 0:
        return None

    min_rr = float(cfg.get("MIN_RR", 2.0))
    sl_mult = float(cfg.get("SL_ATR_MULT", 1.5))
    min_conf = float(cfg.get("MIN_CONFLUENCE", 3.0))

    direction: int | None = None
    setup_type: SetupType | None = None
    confluence = 0.0
    meta: dict[str, Any] = {}

    sweep = _liquidity_sweep(df, swings, i)
    engulf = _engulfing(df, i)
    if sweep and (engulf == sweep or _pin_bar(row, sweep)):
        direction = sweep
        setup_type = SetupType.LIQUIDITY_SWEEP
        confluence += 2.0
        meta["sweep"] = True

    if direction is None and breaks:
        last_br = breaks[-1]
        if last_br.index >= i - 8 and last_br.kind == "bos":
            for ob in reversed(obs):
                if ob.direction != last_br.direction:
                    continue
                if ob.bottom <= price <= ob.top:
                    if engulf == ob.direction or _pin_bar(row, ob.direction):
                        direction = ob.direction
                        setup_type = SetupType.BOS_OB
                        confluence += 2.5
                        meta["ob"] = (ob.bottom, ob.top)
                        break

    if direction is None:
        for gap in reversed(fvgs):
            if gap.filled or gap.index < i - 40:
                continue
            if gap.direction == 1 and trend in (Trend.BULL, Trend.RANGE):
                if gap.bottom <= price <= gap.top and (
                    engulf == 1 or _pin_bar(row, 1)
                ):
                    direction = 1
                    setup_type = SetupType.FVG_FILL
                    confluence += 2.0
                    meta["fvg"] = (gap.bottom, gap.top)
                    break
            if gap.direction == -1 and trend in (Trend.BEAR, Trend.RANGE):
                if gap.bottom <= price <= gap.top and (
                    engulf == -1 or _pin_bar(row, -1)
                ):
                    direction = -1
                    setup_type = SetupType.FVG_FILL
                    confluence += 2.0
                    meta["fvg"] = (gap.bottom, gap.top)
                    break

    if direction is None or setup_type is None:
        return None

    require_sweep = bool(cfg.get("REQUIRE_SWEEP_BEFORE_ENTRY", False))
    if require_sweep and setup_type == SetupType.BOS_OB and not had_recent_sweep(df, swings, i):
        return None

    use_pd = bool(cfg.get("USE_PREMIUM_DISCOUNT", False))
    if use_pd:
        zone = price_zone(df, i)
        if not zone_allows_direction(zone, direction):
            return None
        meta["zone"] = zone

    prefer_choch = bool(cfg.get("PREFER_CHOCH", False))
    if prefer_choch and breaks:
        last_br = breaks[-1]
        if last_br.kind != "choch" and setup_type == SetupType.BOS_OB:
            return None

    if trend == Trend.BULL and direction == 1:
        confluence += 1.0
    elif trend == Trend.BEAR and direction == -1:
        confluence += 1.0
    elif trend == Trend.RANGE:
        confluence += 0.3

    if confluence < min_conf:
        return None

    if direction == 1:
        sl = price - atr * sl_mult
        risk = price - sl
        tp = price + risk * min_rr
    else:
        sl = price + atr * sl_mult
        risk = sl - price
        tp = price - risk * min_rr

    if risk <= 0:
        return None

    rr = abs(tp - price) / risk
    if rr < min_rr:
        return None

    confidence = min(0.95, 0.45 + confluence * 0.08)
    return PriceActionSetup(
        direction=direction,
        setup=setup_type,
        entry=price,
        stop_loss=float(sl),
        take_profit=float(tp),
        confidence=round(confidence, 3),
        confluence=round(confluence, 2),
        metadata={
            **meta,
            "trend": trend.value,
            "rr": round(rr, 2),
            "confluence": confluence,
        },
    )
