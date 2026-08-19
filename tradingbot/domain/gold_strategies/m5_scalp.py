"""M5 gold scalp — kill zone, sweep/BOS+OB, بدون FVG، فیلتر HTF (H4 bias)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.price_action import (
    PriceActionSetup,
    SetupType,
    Trend,
    _engulfing,
    _liquidity_sweep,
    _pin_bar,
    had_recent_sweep,
)


def evaluate_m5_scalp(
    df: pd.DataFrame, i: int, cfg: dict[str, Any]
) -> PriceActionSetup | None:
    if i < 30 or i >= len(df):
        return None

    swings = df.attrs.get("pa_swings", [])
    breaks = df.attrs.get("pa_breaks", [])
    obs = df.attrs.get("pa_obs", [])
    trend: Trend = df.attrs.get("pa_trend", Trend.RANGE)

    row = df.iloc[i]
    price = float(row["close"])
    atr = float(row["atr"]) if not pd.isna(row.get("atr")) else price * 0.001
    if atr <= 0:
        return None

    min_rr = float(cfg.get("MIN_RR", 2.0))
    sl_mult = float(cfg.get("SL_ATR_MULT", 2.3))
    min_conf = float(cfg.get("MIN_CONFLUENCE", 3.0))
    bos_lookback = int(cfg.get("M5_BOS_LOOKBACK", 6))
    sweep_only = bool(cfg.get("M5_SWEEP_ONLY", False))
    require_engulf = bool(cfg.get("M5_REQUIRE_ENGULF", False))
    block_range = bool(cfg.get("M5_BLOCK_RANGE", False))

    direction: int | None = None
    setup_type: SetupType | None = None
    confluence = 0.0
    meta: dict[str, Any] = {"strategy_mode": "m5_scalp"}

    sweep = _liquidity_sweep(df, swings, i)
    engulf = _engulfing(df, i)

    def _sweep_confirm(dir_: int) -> bool:
        if require_engulf:
            return engulf == dir_
        return engulf == dir_ or _pin_bar(row, dir_)

    if sweep and _sweep_confirm(sweep):
        direction = sweep
        setup_type = SetupType.LIQUIDITY_SWEEP
        confluence += 2.5
        meta["sweep"] = True

    if direction is None and not sweep_only and breaks:
        last_br = breaks[-1]
        if last_br.index >= i - bos_lookback and last_br.kind == "bos":
            if had_recent_sweep(df, swings, i, bars=12):
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

    if direction is None or setup_type is None:
        return None

    if block_range and trend == Trend.RANGE:
        return None

    if trend == Trend.BULL and direction == 1:
        confluence += 1.0
    elif trend == Trend.BEAR and direction == -1:
        confluence += 1.0
    elif trend == Trend.RANGE:
        confluence += 0.2

    use_pd = bool(cfg.get("USE_PREMIUM_DISCOUNT", False))
    if use_pd:
        from tradingbot.domain.price_action import price_zone, zone_allows_direction

        zone = price_zone(df, i)
        if not zone_allows_direction(zone, direction):
            return None
        meta["zone"] = zone
        confluence += 0.5

    if confluence < min_conf:
        return None

    low = float(row["low"])
    high = float(row["high"])

    if direction == 1:
        sl_atr = price - atr * sl_mult
        sl_struct = low - atr * 0.15
        sl = min(sl_atr, sl_struct)
        risk = price - sl
        tp = price + risk * min_rr
    else:
        sl_atr = price + atr * sl_mult
        sl_struct = high + atr * 0.15
        sl = max(sl_atr, sl_struct)
        risk = sl - price
        tp = price - risk * min_rr

    if risk <= 0:
        return None

    rr = abs(tp - price) / risk
    if rr < min_rr:
        return None

    confidence = min(0.95, 0.48 + confluence * 0.08)
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
