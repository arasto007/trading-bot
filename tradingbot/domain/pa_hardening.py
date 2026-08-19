"""Phase 1A — PA hardening helpers (BOS, FVG, sweep, quality score)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from tradingbot.domain.price_action import (
    PriceActionSetup,
    SetupType,
    StructureBreak,
    _liquidity_sweep,
    had_recent_sweep,
)

_DEDUP: dict[str, datetime] = {}
_MFE_MAE_BY_SETUP: dict[str, list[dict[str, float]]] = {}


@dataclass
class SetupHardeningAnalysis:
    setup_type: str
    bos_confirmed: bool
    fvg_confirmed: bool
    liquidity_sweep: bool
    quality_score: int
    session: str
    session_range_breakout: bool
    session_range_stats: dict[str, float] = field(default_factory=dict)
    mfe_r: float | None = None
    mae_r: float | None = None


def session_label(ts: datetime) -> str:
    h = ts.hour
    if 0 <= h < 7:
        return "ASIAN"
    if 7 <= h < 12:
        return "LONDON"
    if 12 <= h < 17:
        return "NY"
    if 17 <= h < 21:
        return "NY_LATE"
    return "OFF"


def detect_bos_continuation(breaks: list[StructureBreak], i: int, direction: int) -> bool:
    for br in reversed(breaks):
        if br.index > i or br.index < i - 12:
            continue
        if br.kind == "bos" and br.direction == direction:
            return True
    return False


def detect_choch_continuation(
    df: pd.DataFrame,
    direction: int,
    lookback: int = 8,
    *,
    at_index: int | None = None,
    reclaim_index: int | None = None,
) -> bool:
    """After reclaim, same-direction CHoCH with displacement counts as continuation.

    BUY: last structure event in lookback is choch, bullish, close above the
    broken swing high, displacement >= 0.6 * ATR14, and CHoCH is within
    ``lookback`` bars of reclaim (when reclaim_index is provided).
    SELL is the inverse.
    """
    if df is None or df.empty or int(direction) not in (1, -1):
        return False
    i = len(df) - 1 if at_index is None else int(at_index)
    if i < 1 or i >= len(df):
        return False
    lb = max(1, int(lookback))
    window_start = i - lb
    if reclaim_index is not None:
        rec = int(reclaim_index)
        if rec > i or (i - rec) > lb:
            return False
        window_start = max(window_start, rec)

    breaks = list(df.attrs.get("pa_breaks", []) or [])
    last: StructureBreak | None = None
    for br in reversed(breaks):
        if br.index > i or br.index < window_start:
            continue
        last = br
        break
    if last is None or last.kind != "choch" or int(last.direction) != int(direction):
        return False

    level = float(last.level)
    close_i = float(df["close"].iloc[i])
    close_br = float(df["close"].iloc[last.index])
    if direction == 1:
        if not (close_i > level or close_br > level):
            return False
    else:
        if not (close_i < level or close_br < level):
            return False

    atr = 0.0
    if "atr" in df.columns and not pd.isna(df["atr"].iloc[i]):
        atr = float(df["atr"].iloc[i])
    if atr <= 0:
        atr = abs(close_i) * 0.001
    body = abs(float(df["close"].iloc[last.index]) - float(df["open"].iloc[last.index]))
    if body < 0.6 * max(atr, 1e-9):
        return False
    return True


def confirm_fvg_fill(fvgs: list[Any], *, price: float, direction: int, i: int) -> bool:
    for gap in reversed(fvgs):
        if gap.index > i or gap.index < i - 40:
            continue
        if gap.direction != direction:
            continue
        if gap.bottom <= price <= gap.top:
            return True
    return False


def detect_liquidity_sweep_flag(df: pd.DataFrame, swings: list, i: int) -> bool:
    return _liquidity_sweep(df, swings, i) is not None or had_recent_sweep(df, swings, i)


def session_range_breakout_stats(df: pd.DataFrame, i: int, cfg: dict[str, Any]) -> dict[str, Any]:
    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    start = max(0, i - lookback)
    window = df.iloc[start:i]
    if window.empty:
        return {"range_high": 0.0, "range_low": 0.0, "range_atr": 0.0, "breakout": False}
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    close = float(df["close"].iloc[i])
    atr = float(df["atr"].iloc[i]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[i]) else (hi - lo)
    atr = max(atr, 1e-9)
    range_atr = (hi - lo) / atr
    min_range = float(cfg.get("MIN_RANGE_ATR", 0.2))
    breakout_up = close > hi and range_atr >= min_range
    breakout_down = close < lo and range_atr >= min_range
    return {
        "range_high": hi,
        "range_low": lo,
        "range_atr": round(range_atr, 3),
        "breakout": bool(breakout_up or breakout_down),
        "breakout_direction": 1 if breakout_up else (-1 if breakout_down else 0),
    }


def compute_quality_score(
    *,
    setup: PriceActionSetup,
    bos_confirmed: bool,
    fvg_confirmed: bool,
    liquidity_sweep: bool,
    session_breakout: bool,
    confluence: float,
    choch_confirmed: bool = False,
) -> int:
    score = 40.0
    score += min(20.0, confluence * 4.0)
    if bos_confirmed:
        score += 12.0
    elif choch_confirmed:
        score += 8.0
    if fvg_confirmed:
        score += 10.0
    if liquidity_sweep:
        score += 10.0
    if session_breakout:
        score += 8.0
    if setup.setup == SetupType.LIQUIDITY_SWEEP:
        score += 5.0
    return int(max(0, min(100, round(score))))


def project_mfe_mae_r(
    df: pd.DataFrame,
    i: int,
    *,
    entry: float,
    sl: float,
    direction: int,
    max_bars: int = 24,
) -> tuple[float | None, float | None]:
    risk = abs(entry - sl)
    if risk <= 0 or i >= len(df) - 1:
        return None, None
    end = min(len(df), i + 1 + max_bars)
    mfe = mae = 0.0
    for j in range(i + 1, end):
        row = df.iloc[j]
        hi, lo = float(row["high"]), float(row["low"])
        if direction == 1:
            fav = (hi - entry) / risk
            adv = (entry - lo) / risk
        else:
            fav = (entry - lo) / risk
            adv = (hi - entry) / risk
        mfe = max(mfe, max(0.0, fav))
        mae = max(mae, max(0.0, adv))
    return round(mfe, 4), round(mae, 4)


def apply_setup_hardening(
    df: pd.DataFrame,
    i: int,
    cfg: dict[str, Any],
    setup: PriceActionSetup,
    *,
    timeframe: str,
) -> PriceActionSetup | None:
    min_quality = int(cfg.get("MIN_QUALITY_SCORE", 0))
    swings = df.attrs.get("pa_swings", [])
    breaks = df.attrs.get("pa_breaks", [])
    fvgs = df.attrs.get("pa_fvgs", [])
    ts = df.index[i]
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)

    bos = detect_bos_continuation(breaks, i, setup.direction)
    choch = False
    mode = str(cfg.get("GOLD_STRATEGY_MODE", "") or "").lower()
    london = mode in ("london_sweep", "m5_london_sweep", "asian_sweep")
    if bool(cfg.get("ENABLE_CHOCH_CONTINUATION", False)) and london:
        rec_raw = (setup.metadata or {}).get("reclaim_index")
        rec_i = int(rec_raw) if rec_raw is not None else None
        choch = detect_choch_continuation(
            df,
            setup.direction,
            lookback=8,
            at_index=i,
            reclaim_index=rec_i,
        )
    fvg = confirm_fvg_fill(fvgs, price=setup.entry, direction=setup.direction, i=i)
    sweep = detect_liquidity_sweep_flag(df, swings, i) or setup.setup == SetupType.LIQUIDITY_SWEEP
    sess_stats = session_range_breakout_stats(df, i, cfg)
    quality = compute_quality_score(
        setup=setup,
        bos_confirmed=bos,
        fvg_confirmed=fvg,
        liquidity_sweep=sweep,
        session_breakout=bool(sess_stats.get("breakout")),
        confluence=float(setup.confluence),
        choch_confirmed=bool(choch and not bos),
    )
    if min_quality and quality < min_quality:
        return None

    mfe, mae = project_mfe_mae_r(
        df, i, entry=setup.entry, sl=setup.stop_loss, direction=setup.direction
    )
    setup_type = setup.metadata.get("strategy_mode", setup.setup.value)
    if cfg.get("GOLD_STRATEGY_MODE") == "london_sweep" and sweep:
        setup_type = "london_sweep"

    setup.metadata.update({
        "setup_type": setup_type,
        "bos_confirmed": bos,
        "fvg_confirmed": fvg,
        "liquidity_sweep": sweep,
        "quality_score": quality,
        "session": session_label(ts),
        "session_range_breakout": bool(sess_stats.get("breakout")),
        "session_range_stats": {
            k: float(sess_stats[k])
            for k in ("range_high", "range_low", "range_atr")
            if k in sess_stats
        },
        "mfe_r_projected": mfe,
        "mae_r_projected": mae,
        "timeframe": timeframe,
    })
    if bool(cfg.get("ENABLE_CHOCH_CONTINUATION", False)) and london:
        setup.metadata["choch_confirmed"] = choch
        setup.metadata["continuation_ok"] = bool(bos or choch)
    if mfe is not None:
        _MFE_MAE_BY_SETUP.setdefault(setup_type, []).append({"mfe_r": mfe, "mae_r": mae or 0.0})
    return setup


def is_duplicate_pa_signal(
    symbol: str,
    direction: int,
    bar_time: Any,
    *,
    cooldown_minutes: int = 10,
) -> bool:
    now = datetime.now(timezone.utc)
    if hasattr(bar_time, "to_pydatetime"):
        bar_time = bar_time.to_pydatetime()
    if getattr(bar_time, "tzinfo", None) is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    key = f"{symbol.upper()}|{direction}|{bar_time.isoformat()}"
    prev = _DEDUP.get(key)
    if prev is not None and now - prev < timedelta(minutes=cooldown_minutes):
        return True
    _DEDUP[key] = now
    return False


def clear_pa_dedup_cache() -> None:
    _DEDUP.clear()


def mfe_mae_stats_by_setup() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for setup_type, rows in _MFE_MAE_BY_SETUP.items():
        if not rows:
            continue
        mfes = [r["mfe_r"] for r in rows]
        maes = [r["mae_r"] for r in rows]
        out[setup_type] = {
            "count": len(rows),
            "avg_mfe_r": round(sum(mfes) / len(mfes), 3),
            "avg_mae_r": round(sum(maes) / len(maes), 3),
        }
    return out
