"""
M5 London Asian-range sweep — استراتژی جدا از M15 SMC.

منطق (ICT / Pro-Scalper):
  1) رنج آسیا (00:00–07:00 UTC) را روی M5 می‌سازیم
  2) در باز شدن لندن (07:00–10:00 UTC) sweep بالای/پایین رنج
  3) ورود وقتی کندل M5 داخل رنج بسته شود (fake breakout)
  4) SL پشت extreme سوئیپ، TP طرف مقابل رنج یا RR
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from tradingbot.domain.price_action import (
    PriceActionSetup,
    SetupType,
    _engulfing,
    _pin_bar,
)
from tradingbot.domain.pa_hardening import (
    detect_bos_continuation,
    detect_choch_continuation,
)


def _ts(index: pd.Index, i: int):
    ts = index[i]
    if hasattr(ts, "to_pydatetime"):
        return ts.to_pydatetime()
    return pd.Timestamp(ts).to_pydatetime()


def _day(index: pd.Index, i: int) -> date:
    return _ts(index, i).date()


def _hour(index: pd.Index, i: int) -> int:
    return _ts(index, i).hour


def asian_range(
    df: pd.DataFrame,
    i: int,
    *,
    start_hour: int = 0,
    end_hour: int = 7,
    min_bars: int = 4,
) -> tuple[float, float] | None:
    """High/low رنج آسیا همان روز UTC."""
    if i < min_bars:
        return None
    day = _day(df.index, i)
    idxs: list[int] = []
    for j in range(i):
        if _day(df.index, j) != day:
            continue
        h = _hour(df.index, j)
        if start_hour <= h < end_hour:
            idxs.append(j)
    if len(idxs) < min_bars:
        return None
    window = df.iloc[idxs]
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    if hi <= lo:
        return None
    return hi, lo


def m5_asian_end_hour(cfg: dict[str, Any]) -> int:
    return int(cfg.get("ASIAN_SESSION_END_UTC", cfg.get("ASIAN_END_HOUR", 7)))


def m5_ny_entry_hours(cfg: dict[str, Any]) -> tuple[int, int]:
    start = int(cfg.get("NY_ENTRY_START_UTC", cfg.get("NY_ENTRY_START_HOUR", 12)))
    end = int(cfg.get("NY_ENTRY_END_UTC", cfg.get("NY_ENTRY_END_HOUR", 15)))
    return start, end


def m5_hour15_telemetry(cfg: dict[str, Any]) -> dict[str, Any]:
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    asian_end = m5_asian_end_hour(cfg)
    return {
        "hour15_mode": bool(ny_s == 15 and ny_e == 16),
        "asian_end_utc": asian_end,
    }


def _in_entry_window(df: pd.DataFrame, i: int, cfg: dict[str, Any]) -> bool:
    h = _hour(df.index, i)
    if bool(cfg.get("M5_USE_LONDON_SESSION", True)):
        london_s = int(cfg.get("LONDON_ENTRY_START_HOUR", 7))
        london_e = int(cfg.get("LONDON_ENTRY_END_HOUR", 10))
        if london_s <= h < london_e:
            return True
    if bool(cfg.get("M5_USE_NY_SESSION", False)):
        ny_s, ny_e = m5_ny_entry_hours(cfg)
        if ny_s <= h < ny_e:
            return True
    return False


def diagnose_m5_london_hold(
    df: pd.DataFrame, i: int, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Observability-only mirror of evaluate_m5_london_sweep failure points.

    Does not affect trading decisions. Returns hold telemetry fields.
    """
    out: dict[str, Any] = {
        "session_ok": False,
        "asian_range_built": False,
        "sweep_detected": False,
        "reclaim_detected": False,
        "bos_detected": False,
        "fvg_detected": False,
        "confidence_score": 0.0,
        "reject_reason": "warmup_or_oob",
    }
    if i < 30 or i >= len(df):
        return out

    session_ok = _in_entry_window(df, i, cfg)
    out["session_ok"] = session_ok
    if not session_ok:
        out["reject_reason"] = "outside_ny_entry_window"
        return out

    asian_start = int(cfg.get("ASIAN_START_HOUR", 0))
    asian_end = m5_asian_end_hour(cfg)
    bounds = asian_range(
        df, i, start_hour=asian_start, end_hour=asian_end, min_bars=4
    )
    if bounds is None:
        out["reject_reason"] = "no_asian_range"
        return out
    asian_hi, asian_lo = bounds
    out["asian_range_built"] = True

    row = df.iloc[i]
    price = float(row["close"])
    atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else price * 0.001
    if atr <= 0:
        out["reject_reason"] = "atr_invalid"
        return out

    min_range = atr * float(cfg.get("MIN_RANGE_ATR", 0.25))
    if (asian_hi - asian_lo) < min_range:
        out["reject_reason"] = "no_asian_range"
        return out

    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf = atr * float(cfg.get("SWEEP_BUFFER_ATR", 0.15))
    start_j = max(0, i - lookback)
    window = df.iloc[start_j : i + 1]
    win_high = float(window["high"].max())
    win_low = float(window["low"].min())

    swept_hi = win_high > asian_hi + buf
    swept_lo = win_low < asian_lo - buf
    sweep_detected = bool(swept_hi or swept_lo)
    inside = asian_lo < price < asian_hi
    out["sweep_detected"] = sweep_detected
    out["reclaim_detected"] = bool(sweep_detected and inside)

    min_rr = float(cfg.get("MIN_RR", 1.8))
    sl_pad = atr * float(cfg.get("SL_ATR_MULT", 0.35))
    direction: int | None = None
    risk = 0.0
    tp = 0.0
    if swept_hi and inside and float(row["close"]) < asian_hi:
        direction = -1
        sl = win_high + sl_pad
        risk = sl - price
        tp = price - max(price - asian_lo, risk * min_rr)
    elif swept_lo and inside and float(row["close"]) > asian_lo:
        direction = 1
        sl = win_low - sl_pad
        risk = price - sl
        tp = price + max(asian_hi - price, risk * min_rr)

    if direction is None and bool(cfg.get("ENABLE_CHOCH_CONTINUATION", False)):
        rec_j: int | None = None
        rec_dir: int | None = None
        start_rec = max(0, i - 8)
        for j in range(start_rec, i + 1):
            cj = float(df["close"].iloc[j])
            if swept_hi and asian_lo < cj < asian_hi:
                rec_j = j
                rec_dir = -1
            elif swept_lo and asian_lo < cj < asian_hi:
                rec_j = j
                rec_dir = 1
        if rec_j is not None and rec_dir is not None and detect_choch_continuation(
            df, rec_dir, lookback=8, at_index=i, reclaim_index=rec_j
        ):
            direction = rec_dir
            out["reclaim_detected"] = True
            if rec_dir < 0:
                sl = win_high + sl_pad
                risk = sl - price
                tp = price - max(max(price - asian_lo, 0.0), risk * min_rr)
            else:
                sl = win_low - sl_pad
                risk = price - sl
                tp = price + max(max(asian_hi - price, 0.0), risk * min_rr)

    if direction is None:
        if not sweep_detected:
            out["reject_reason"] = "no_sweep"
        elif not inside:
            out["reject_reason"] = "no_reclaim_inside_asian"
        else:
            out["reject_reason"] = "no_reclaim_inside_asian"
        return out

    require_reject = bool(cfg.get("M5_REQUIRE_REJECTION", True))
    if require_reject and not (
        _engulfing(df, i) == direction or _pin_bar(row, direction)
    ):
        out["reject_reason"] = "rejection_candle_fail"
        return out
    if risk <= 0:
        out["reject_reason"] = "risk_invalid"
        return out
    rr = abs(tp - price) / risk
    if rr < min_rr * 0.95:
        out["reject_reason"] = "rr_below_min"
        return out

    confidence = round(min(0.92, 0.55 + min(rr, 3.0) * 0.08), 3)
    out["confidence_score"] = confidence
    out["reject_reason"] = "setup_ok_pre_hardening"
    return out


def evaluate_m5_london_sweep(
    df: pd.DataFrame, i: int, cfg: dict[str, Any]
) -> PriceActionSetup | None:
    if i < 30 or i >= len(df):
        return None

    if not _in_entry_window(df, i, cfg):
        return None

    asian_start = int(cfg.get("ASIAN_START_HOUR", 0))
    asian_end = m5_asian_end_hour(cfg)
    bounds = asian_range(
        df, i, start_hour=asian_start, end_hour=asian_end, min_bars=4
    )
    if bounds is None:
        return None
    asian_hi, asian_lo = bounds

    row = df.iloc[i]
    price = float(row["close"])
    atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else price * 0.001
    if atr <= 0:
        return None

    min_range = atr * float(cfg.get("MIN_RANGE_ATR", 0.25))
    if (asian_hi - asian_lo) < min_range:
        return None

    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf = atr * float(cfg.get("SWEEP_BUFFER_ATR", 0.15))
    start_j = max(0, i - lookback)
    window = df.iloc[start_j : i + 1]
    win_high = float(window["high"].max())
    win_low = float(window["low"].min())

    min_rr = float(cfg.get("MIN_RR", 1.8))
    sl_pad = atr * float(cfg.get("SL_ATR_MULT", 0.35))

    direction: int | None = None
    sl = tp = 0.0
    risk = 0.0
    meta: dict[str, Any] = {
        "strategy_mode": "m5_london_sweep",
        "asian_high": asian_hi,
        "asian_low": asian_lo,
        **m5_hour15_telemetry(cfg),
    }

    # Sweep بالا → فروش (برگشت داخل رنج)
    if (
        win_high > asian_hi + buf
        and asian_lo < price < asian_hi
        and float(row["close"]) < asian_hi
    ):
        direction = -1
        meta["sweep_side"] = "high"
        if bool(cfg.get("ENABLE_CHOCH_CONTINUATION", False)):
            meta["entry_path"] = "reclaim"
            meta["reclaim_index"] = i
        sl = win_high + sl_pad
        risk = sl - price
        tp_range = price - asian_lo
        tp_rr = risk * min_rr
        tp = price - max(tp_range, tp_rr)

    # Sweep پایین → خرید
    elif (
        win_low < asian_lo - buf
        and asian_lo < price < asian_hi
        and float(row["close"]) > asian_lo
    ):
        direction = 1
        meta["sweep_side"] = "low"
        if bool(cfg.get("ENABLE_CHOCH_CONTINUATION", False)):
            meta["entry_path"] = "reclaim"
            meta["reclaim_index"] = i
        sl = win_low - sl_pad
        risk = price - sl
        tp_range = asian_hi - price
        tp_rr = risk * min_rr
        tp = price + max(tp_range, tp_rr)

    elif bool(cfg.get("ENABLE_CHOCH_CONTINUATION", False)):
        rec_j: int | None = None
        rec_dir: int | None = None
        start_rec = max(0, i - 8)
        for j in range(start_rec, i + 1):
            cj = float(df["close"].iloc[j])
            if win_high > asian_hi + buf and asian_lo < cj < asian_hi:
                rec_j = j
                rec_dir = -1
            elif win_low < asian_lo - buf and asian_lo < cj < asian_hi:
                rec_j = j
                rec_dir = 1
        if rec_j is not None and rec_dir is not None and detect_choch_continuation(
            df, rec_dir, lookback=8, at_index=i, reclaim_index=rec_j
        ):
            direction = rec_dir
            meta["entry_path"] = "choch_continuation"
            meta["reclaim_index"] = rec_j
            meta["sweep_side"] = "high" if rec_dir < 0 else "low"
            if rec_dir < 0:
                sl = win_high + sl_pad
                risk = sl - price
                tp_range = max(price - asian_lo, 0.0)
                tp = price - max(tp_range, risk * min_rr)
            else:
                sl = win_low - sl_pad
                risk = price - sl
                tp_range = max(asian_hi - price, 0.0)
                tp = price + max(tp_range, risk * min_rr)
        else:
            return None
    else:
        return None

    require_reject = bool(cfg.get("M5_REQUIRE_REJECTION", True))
    if require_reject and not (
        _engulfing(df, i) == direction or _pin_bar(row, direction)
    ):
        return None

    if risk <= 0:
        return None

    rr = abs(tp - price) / risk
    if rr < min_rr * 0.95:
        return None

    confidence = min(0.92, 0.55 + min(rr, 3.0) * 0.08)
    extra: dict[str, Any] = {"rr": round(rr, 2)}
    if bool(cfg.get("ENABLE_CHOCH_CONTINUATION", False)):
        breaks = list(df.attrs.get("pa_breaks", []) or [])
        bos_ok = detect_bos_continuation(breaks, i, direction)
        rec_i = meta.get("reclaim_index", i)
        choch_ok = detect_choch_continuation(
            df, direction, lookback=8, at_index=i, reclaim_index=int(rec_i)
        )
        extra["bos_ok"] = bos_ok
        extra["choch_ok"] = choch_ok
        extra["continuation_ok"] = bool(bos_ok or choch_ok)
    return PriceActionSetup(
        direction=direction,
        setup=SetupType.LIQUIDITY_SWEEP,
        entry=price,
        stop_loss=float(sl),
        take_profit=float(tp),
        confidence=round(confidence, 3),
        confluence=3.2,
        metadata={**meta, **extra},
    )
