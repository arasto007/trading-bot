"""Phase 7A — Adaptive Quality v2 research (dynamic weights + threshold sweep)."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase3a.vol_edge_research import regime_cluster
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
from tradingbot.strategies.adaptive_quality_engine import (
    ATR_BAND,
    _is_london,
    _vol_component,
    resolve_candidate_direction,
)
from tradingbot.strategies.adaptive_regime import (
    MIN_EMA_SEP,
    MIN_H1_TREND,
    _bar_open_hour_utc,
    _ema_sep_ok,
    _h1_aligned,
    _in_session,
    classify_regime,
    prepare_adaptive_frame,
)

WATCHLIST_FLOOR = 60
WATCHLIST_CEIL = 69
THRESHOLDS = (65, 68, 70, 72, 75)

WEIGHT_GRID = {
    "h1": (20, 25, 30, 35),
    "atr": (10, 15, 20, 25),
    "ema": (15, 20, 25),
    "session": (0, 10, 20),
    "vol": (0, 10, 20),
}


def _pf_num(pf: Any) -> float:
    if pf in ("inf", float("inf")):
        return 999.0
    return float(pf)


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "pf": 0.0,
            "expectancy_r": 0.0,
            "max_dd_r": 0.0,
        }
    rs = [float(t["r_multiple"]) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(rs) * 100, 2),
        "pf": round(pf, 3) if pf != 999.0 else "inf",
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "max_dd_r": round(mdd, 2),
    }


def _loss_regime_dominance(trades: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [t for t in trades if float(t["r_multiple"]) < 0]
    if not losses:
        return {"dominant_regime": None, "dominant_pct": 0.0, "passes": True}
    counts: dict[str, int] = {}
    for t in losses:
        reg = str(t.get("regime", "UNKNOWN"))
        counts[reg] = counts.get(reg, 0) + 1
    dominant = max(counts, key=counts.get)
    pct = counts[dominant] / len(losses) * 100.0
    return {
        "dominant_regime": dominant,
        "dominant_pct": round(pct, 2),
        "passes": pct <= 70.0,
        "breakdown": counts,
    }


@dataclass(frozen=True)
class ScoreWeights:
    h1: int
    atr: int
    ema: int
    session: int
    vol: int

    @property
    def key(self) -> str:
        return f"h1{self.h1}_atr{self.atr}_ema{self.ema}_ses{self.session}_vol{self.vol}"


def _h1_fraction(row: pd.Series, direction: int) -> float:
    if not MIN_H1_TREND or _h1_aligned(row, direction):
        return 1.0
    h1 = int(row.get("h1_trend", 0))
    return 0.5 if h1 == 0 else 0.0


def _atr_fraction(row: pd.Series) -> float:
    atr_pct = float(row.get("atr_pct", np.nan))
    if not np.isfinite(atr_pct):
        return 0.0
    lo, hi = ATR_BAND
    if not (lo <= atr_pct <= hi):
        return 0.0
    center = (lo + hi) / 2.0
    half = (hi - lo) / 2.0
    return float(np.clip(1.0 - abs(atr_pct - center) / half, 0.0, 1.0))


def _ema_fraction(row: pd.Series) -> float:
    if _ema_sep_ok(row):
        return 1.0
    sep = float(row.get("ema_sep_pct", 0) or 0)
    if sep >= MIN_EMA_SEP:
        return 1.0
    if sep >= MIN_EMA_SEP * 0.5:
        return 0.65
    return 0.35 if sep > 0 else 0.0


def _session_fraction(bar_open: pd.Timestamp) -> float:
    if _is_london(bar_open):
        return 1.0
    hour = _bar_open_hour_utc(bar_open)
    if 12 <= hour < 17:
        return 0.65
    if 10 <= hour < 17:
        return 0.45
    return 0.0


def _vol_fraction(frame: pd.DataFrame, idx: int, direction: int) -> float:
    raw = _vol_component(frame, idx, direction)
    return float(raw) / 15.0 if raw else 0.0


def _resolve_outcome(
    df: pd.DataFrame,
    i: int,
    d: int,
    price: float,
    atr: float,
    *,
    cache: dict[tuple, dict[str, Any]],
) -> dict[str, Any]:
    sl_mult, rr = 2.2, 1.6
    sl_dist = atr * sl_mult
    if d > 0:
        sl = price - sl_dist
        tp = price + sl_dist * rr
    else:
        sl = price + sl_dist
        tp = price - sl_dist * rr
    key = (i, d, round(price, 3), round(sl, 3), round(tp, 3))
    if key in cache:
        return cache[key]
    outcome = resolve_label_with_sl_tp(df, i, d, sl, tp, future_window_bars=72, entry_price=price)
    sl_d = abs(price - sl)
    if outcome.get("exit_reason") == "tp" and sl_d > 0:
        r_mult = abs(tp - price) / sl_d
    elif outcome.get("exit_reason") == "sl":
        r_mult = -1.0
    else:
        r_mult = 0.0
    hold = int(outcome.get("bars", 1) or 1)
    result = {"r_multiple": round(r_mult, 3), "exit_reason": outcome.get("exit_reason"), "hold_bars": hold}
    cache[key] = result
    return result


def precompute_candidates(
    df: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    warmup: int = 500,
) -> tuple[list[dict[str, Any]], dict[tuple, dict[str, Any]]]:
    n = len(frame)
    bar_range = (frame["high"] - frame["low"]).astype(float)
    roll_med = bar_range.rolling(20, min_periods=5).median()
    atr14 = frame["atr14"].astype(float)
    outcome_cache: dict[tuple, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []

    for i in range(max(warmup, 60), n - 1):
        row = frame.iloc[i]
        regime = classify_regime(row)
        if regime == "NO_TRADE":
            continue
        if not _in_session(row, regime, bar_open=pd.Timestamp(frame.index[i])):
            continue
        direction = resolve_candidate_direction(frame, i)
        if direction is None:
            continue

        bar_open = pd.Timestamp(frame.index[i])
        fracs = {
            "h1": _h1_fraction(row, direction),
            "atr": _atr_fraction(row),
            "ema": _ema_fraction(row),
            "session": _session_fraction(bar_open),
            "vol": _vol_fraction(frame, i, direction),
        }
        j = i + 1
        next_row = frame.iloc[j]
        close_i = float(row["close"])
        close_j = float(next_row["close"])
        dir_ok = (close_j > close_i) if direction > 0 else (close_j < close_i)
        spread_ok = float(bar_range.iloc[i]) <= float(roll_med.iloc[i]) if np.isfinite(roll_med.iloc[i]) else True
        atr_prev = float(atr14.iloc[i]) if np.isfinite(atr14.iloc[i]) else 0.0
        atr_next = float(atr14.iloc[j]) if np.isfinite(atr14.iloc[j]) else 0.0
        atr_ok = atr_next >= atr_prev * 0.90 if atr_prev > 0 else True
        watchlist_ok = bool(dir_ok and spread_ok and atr_ok)

        direct_out = _resolve_outcome(df, i, direction, close_i, atr_prev, cache=outcome_cache)
        watch_out = _resolve_outcome(df, j, direction, close_j, float(atr14.iloc[j]), cache=outcome_cache)

        candidates.append({
            "bar_index": i,
            "entry_index": j,
            "bar_time": str(frame.index[i]),
            "day": str(pd.Timestamp(frame.index[i]).date()),
            "direction": int(direction),
            "regime": regime,
            "regime_cluster": regime_cluster(float(row.get("atr_pct", 0.5))),
            "fracs": fracs,
            "watchlist_ok": watchlist_ok,
            "direct_outcome": direct_out,
            "watch_outcome": watch_out,
        })
    return candidates, outcome_cache


def score_bar(fracs: dict[str, float], weights: ScoreWeights) -> int:
    total = (
        fracs["h1"] * weights.h1
        + fracs["atr"] * weights.atr
        + fracs["ema"] * weights.ema
        + fracs["session"] * weights.session
        + fracs["vol"] * weights.vol
    )
    return int(round(total))


def build_trades_from_candidates(
    candidates: list[dict[str, Any]],
    weights: ScoreWeights,
    threshold: int,
    *,
    cooldown_bars: int = 8,
    max_trades_per_day: int = 4,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    open_until = last = -9999
    day_counts: dict[str, int] = {}

    for c in candidates:
        sc = score_bar(c["fracs"], weights)
        if sc >= threshold:
            mode = "direct"
            i = int(c["bar_index"])
            outcome = c["direct_outcome"]
        elif WATCHLIST_FLOOR <= sc <= WATCHLIST_CEIL and sc < threshold and c["watchlist_ok"]:
            mode = "watchlist_confirmed"
            i = int(c["entry_index"])
            outcome = c["watch_outcome"]
        else:
            continue

        if i <= open_until or i - last < cooldown_bars:
            continue
        day = c["day"]
        if day_counts.get(day, 0) >= max_trades_per_day:
            continue

        hold = int(outcome.get("hold_bars", 1) or 1)
        open_until = i + max(hold, 1)
        last = i
        day_counts[day] = day_counts.get(day, 0) + 1
        trades.append({
            **c,
            "quality_score": sc,
            "entry_mode": mode,
            "r_multiple": outcome["r_multiple"],
            "exit_reason": outcome.get("exit_reason"),
        })
    return trades


def passes_cert(metrics: dict[str, Any], loss_dom: dict[str, Any]) -> bool:
    return (
        int(metrics["trades"]) >= 150
        and _pf_num(metrics["pf"]) >= 1.30
        and float(metrics["expectancy_r"]) >= 0.12
        and float(metrics["max_dd_r"]) <= 15.0
        and bool(loss_dom.get("passes", False))
    )


def iter_weight_combos() -> list[ScoreWeights]:
    keys = ["h1", "atr", "ema", "session", "vol"]
    combos = []
    for vals in product(*[WEIGHT_GRID[k] for k in keys]):
        combos.append(ScoreWeights(h1=vals[0], atr=vals[1], ema=vals[2], session=vals[3], vol=vals[4]))
    return combos


def run_grid_search(
    df: pd.DataFrame,
    *,
    warmup: int = 500,
) -> dict[str, Any]:
    frame = prepare_adaptive_frame(df)
    candidates, _ = precompute_candidates(df, frame, warmup=warmup)

    baseline_weights = ScoreWeights(h1=30, atr=20, ema=20, session=15, vol=15)
    baseline_trades = build_trades_from_candidates(candidates, baseline_weights, 70)
    baseline_m = _metrics(baseline_trades)

    matrix: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    best_rank = (-1, -1.0, -1.0, -999.0)

    for weights in iter_weight_combos():
        for threshold in THRESHOLDS:
            trades = build_trades_from_candidates(candidates, weights, threshold)
            m = _metrics(trades)
            loss_dom = _loss_regime_dominance(trades)
            certified = passes_cert(m, loss_dom)
            row = {
                "weights": {
                    "h1": weights.h1,
                    "atr": weights.atr,
                    "ema": weights.ema,
                    "session": weights.session,
                    "vol": weights.vol,
                },
                "weights_key": weights.key,
                "threshold": threshold,
                "signals": len(trades),
                **m,
                "loss_dominance": loss_dom,
                "certified": certified,
            }
            matrix.append(row)
            rank = (
                1 if certified else 0,
                _pf_num(m["pf"]),
                float(m["expectancy_r"]),
                -float(m["max_dd_r"]),
            )
            if rank > best_rank:
                best_rank = rank
                best = row

    winners = [r for r in matrix if r["certified"]]
    return {
        "bars": len(df),
        "warmup": warmup,
        "candidate_bars": len(candidates),
        "baseline_v1_equiv": {
            "weights": baseline_weights.key,
            "threshold": 70,
            "metrics": baseline_m,
        },
        "combinations_tested": len(matrix),
        "winners_count": len(winners),
        "winners": winners[:20],
        "best": best,
        "matrix": matrix,
    }
