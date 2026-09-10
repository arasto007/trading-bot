"""Phase 6A — VOL v2 EXPANSION-only research profile (no live enable)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.domain.position_logic import pip_size
from tradingbot.ml.research.phase3a.vol_edge_research import (
    _metrics,
    _pf_num,
    monte_carlo,
    regime_breakdown,
    regime_cluster,
    scan_vol_candidates,
)
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp

VOL_V2_PROFILE: dict[str, Any] = {
    "config_id": "VOL_V2_EXPANSION",
    "session_utc": (7, 12),
    "regime": "EXPANSION",
    "atr_pct_min": 50,
    "atr_pct_max": 75,
    "sl_atr_mult": 1.2,
    "tp_rr": 1.2,
    "cooldown_bars": 10,
    "max_trades_per_day": 3,
}

BASE_SPREAD_PIPS = 4.0
STRESS_SCENARIOS: tuple[tuple[str, float, float], ...] = (
    ("spread_x1.5", 1.5, 0.0),
    ("spread_x2.0", 2.0, 0.0),
    ("slippage_0.3", 1.0, 0.3),
    ("slippage_0.5", 1.0, 0.5),
)


@dataclass(frozen=True)
class VolV2Profile:
    session_lo: int = 7
    session_hi: int = 12
    atr_lo: int = 50
    atr_hi: int = 75
    sl_atr: float = 1.2
    rr: float = 1.2
    cooldown_bars: int = 10
    max_trades_per_day: int = 3
    required_regime: str = "EXPANSION"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VolV2Profile":
        sess = tuple(raw.get("session_utc", (7, 12)))
        return cls(
            session_lo=int(sess[0]),
            session_hi=int(sess[1]),
            atr_lo=int(raw.get("atr_pct_min", 50)),
            atr_hi=int(raw.get("atr_pct_max", 75)),
            sl_atr=float(raw.get("sl_atr_mult", 1.2)),
            rr=float(raw.get("tp_rr", 1.2)),
            cooldown_bars=int(raw.get("cooldown_bars", 10)),
            max_trades_per_day=int(raw.get("max_trades_per_day", 3)),
            required_regime=str(raw.get("regime", "EXPANSION")),
        )


def _atr_pct_value(raw: float) -> float:
    """Normalize ATR percentile to 0–100 scale."""
    v = float(raw)
    return v * 100.0 if v <= 1.0 else v


def simulate_vol_v2(
    df: pd.DataFrame,
    candidates: list[dict[str, Any]],
    profile: VolV2Profile | None = None,
) -> list[dict[str, Any]]:
    """Replay VOL v2 EXPANSION profile on pre-scanned candidates."""
    p = profile or VolV2Profile.from_dict(VOL_V2_PROFILE)
    atr_lo = p.atr_lo / 100.0
    atr_hi = p.atr_hi / 100.0
    trades: list[dict[str, Any]] = []
    open_until = last = -9999
    day_counts: dict[str, int] = {}

    for c in candidates:
        i = int(c["bar_index"])
        if i <= open_until or i - last < p.cooldown_bars:
            continue

        atr_pct = float(c["atr_pct"])
        if not (atr_lo <= atr_pct <= atr_hi):
            continue

        regime = str(c.get("regime") or regime_cluster(atr_pct))
        if regime != p.required_regime:
            continue

        hour = int(c["hour"])
        if not (p.session_lo <= hour < p.session_hi):
            continue

        day = str(pd.Timestamp(c["bar_time"]).date())
        if day_counts.get(day, 0) >= p.max_trades_per_day:
            continue

        price = float(c["entry"])
        atr = float(c["atr14"])
        d = int(c["direction"])
        sl_dist = atr * p.sl_atr
        if d > 0:
            sl = price - sl_dist
            tp = price + sl_dist * p.rr
        else:
            sl = price + sl_dist
            tp = price - sl_dist * p.rr

        outcome = resolve_label_with_sl_tp(
            df, i, d, sl, tp, future_window_bars=72, entry_price=price
        )
        sl_d = abs(price - sl)
        if outcome.get("exit_reason") == "tp" and sl_d > 0:
            r_mult = abs(tp - price) / sl_d
        elif outcome.get("exit_reason") == "sl":
            r_mult = -1.0
        else:
            r_mult = 0.0
        hold = int(outcome.get("bars", 1) or 1)
        open_until = i + max(hold, 1)
        last = i
        day_counts[day] = day_counts.get(day, 0) + 1

        trades.append(
            {
                **c,
                "stop_loss": sl,
                "take_profit": tp,
                "sl_atr": p.sl_atr,
                "rr": p.rr,
                "session": f"{p.session_lo}-{p.session_hi}_UTC",
                "atr_band": f"{p.atr_lo}-{p.atr_hi}",
                "r_multiple": round(r_mult, 3),
                "hold_bars": hold,
                "exit_reason": outcome.get("exit_reason"),
                "variant": VOL_V2_PROFILE["config_id"],
                "atr_pct_display": round(_atr_pct_value(atr_pct), 2),
            }
        )
    return trades


def metrics_with_hold(trades: list[dict[str, Any]]) -> dict[str, Any]:
    m = _metrics(trades)
    if not trades:
        m["average_hold_bars"] = 0.0
        return m
    holds = [float(t.get("hold_bars", 0)) for t in trades]
    m["average_hold_bars"] = round(sum(holds) / len(holds), 2)
    return m


def apply_execution_stress(
    trades: list[dict[str, Any]],
    *,
    spread_mult: float = 1.0,
    slippage_pips: float = 0.0,
    symbol: str = "XAUUSD",
) -> list[dict[str, Any]]:
    """Adjust R-multiples for round-trip spread + slippage."""
    ps = pip_size(symbol)
    spread = BASE_SPREAD_PIPS * spread_mult
    out: list[dict[str, Any]] = []
    for t in trades:
        entry = float(t["entry"])
        sl = float(t["stop_loss"])
        stop_pips = abs(entry - sl) / ps if ps > 0 else 0.0
        if stop_pips <= 0:
            continue
        cost_r = (2.0 * spread + 2.0 * slippage_pips) / stop_pips
        r_raw = float(t["r_multiple"])
        if r_raw > 0:
            r_adj = r_raw - cost_r
        elif r_raw < 0:
            r_adj = r_raw - cost_r
        else:
            r_adj = -cost_r
        out.append({**t, "r_multiple": round(r_adj, 3), "stress_cost_r": round(cost_r, 4)})
    return out


def run_stress_battery(trades: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name, spread_mult, slip in STRESS_SCENARIOS:
        stressed = apply_execution_stress(trades, spread_mult=spread_mult, slippage_pips=slip)
        m = metrics_with_hold(stressed)
        rows.append({"scenario": name, "spread_mult": spread_mult, "slippage_pips": slip, **m})
    pf_values = [_pf_num(r["pf"]) for r in rows if int(r["trades"]) > 0]
    worst_pf = min(pf_values) if pf_values else 0.0
    return {"scenarios": rows, "stress_pf_min": round(worst_pf, 3)}


def passes_vol_v2_cert(
    metrics: dict[str, Any],
    mc: dict[str, Any],
    stress_pf: float,
) -> bool:
    return (
        int(metrics["trades"]) >= 80
        and _pf_num(metrics["pf"]) >= 1.25
        and float(metrics["expectancy_r"]) > 0.15
        and float(metrics["max_dd_r"]) < 12.0
        and float(mc.get("pf_median", 0)) > 1.15
        and float(stress_pf) >= 1.05
    )


def run_vol_v2_research(
    df: pd.DataFrame,
    *,
    warmup: int = 500,
    simulations: int = 1000,
) -> dict[str, Any]:
    candidates = scan_vol_candidates(df, warmup=warmup)
    profile = VolV2Profile.from_dict(VOL_V2_PROFILE)
    trades = simulate_vol_v2(df, candidates, profile)
    metrics = metrics_with_hold(trades)
    mc = monte_carlo(trades, simulations=simulations)
    reg = regime_breakdown(trades)
    stress = run_stress_battery(trades)
    certified = passes_vol_v2_cert(metrics, mc, stress["stress_pf_min"])
    return {
        "profile": VOL_V2_PROFILE,
        "candidates": len(candidates),
        "trades_raw": trades,
        "metrics": metrics,
        "regime_breakdown": reg,
        "monte_carlo": mc,
        "stress": stress,
        "certified": certified,
        "recommended_for_router": certified,
    }
