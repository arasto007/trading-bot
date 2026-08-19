"""Phase 4A — Adaptive quality engine backtest comparison (old AND-gate vs quality score)."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.strategies.adaptive_quality_engine import (
    TRADEABLE_MIN,
    WATCHLIST_MIN,
    compute_quality_score,
    evaluate_quality_at_index,
    resolve_candidate_direction,
)
from tradingbot.strategies.adaptive_regime import (
    evaluate_adaptive_at_index,
    prepare_adaptive_frame,
)


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


def _pf_num(pf: Any) -> float:
    if pf in ("inf", float("inf")):
        return 999.0
    return float(pf)


def _simulate_trades(
    df: pd.DataFrame,
    frame: pd.DataFrame,
    signals: list[dict[str, Any]],
    *,
    cooldown_bars: int = 8,
    max_trades_per_day: int = 4,
) -> list[dict[str, Any]]:
    from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp

    trades: list[dict[str, Any]] = []
    open_until = last = -9999
    day_counts: dict[str, int] = {}

    for sig in signals:
        i = int(sig["bar_index"])
        if i <= open_until or i - last < cooldown_bars:
            continue
        day = str(pd.Timestamp(sig["bar_time"]).date())
        if day_counts.get(day, 0) >= max_trades_per_day:
            continue

        price = float(sig["entry"])
        atr = float(frame.iloc[i]["atr14"])
        d = int(sig["direction"])
        sl_mult = float(sig["sl_atr"])
        rr = float(sig["rr"])
        sl_dist = atr * sl_mult
        if d > 0:
            sl = price - sl_dist
            tp = price + sl_dist * rr
        else:
            sl = price + sl_dist
            tp = price - sl_dist * rr

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
        trades.append({**sig, "r_multiple": round(r_mult, 3), "exit_reason": outcome.get("exit_reason")})
    return trades


def _collect_old_signals(
    df: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    warmup: int = 500,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    signals: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    for i in range(max(warmup, 60), len(frame)):
        sig = evaluate_adaptive_at_index(frame, i, log_rejections=False, use_quality_engine=False)
        if sig is None:
            rejections["no_signal"] += 1
            continue
        row = frame.iloc[i]
        signals.append({
            "bar_index": i,
            "bar_time": str(frame.index[i]),
            "direction": int(sig.direction),
            "entry": float(row["close"]),
            "sl_atr": float(sig.atr_sl_mult),
            "rr": float(sig.tp_rr),
            "regime": sig.regime,
            "strategy_id": sig.strategy_id,
            "engine": "old",
        })
    return signals, rejections


def _collect_new_signals(
    df: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    warmup: int = 500,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    signals: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    for i in range(max(warmup, 60), len(frame)):
        score, ctx = evaluate_quality_at_index(frame, i, log_rejections=False)
        if score is None:
            reason = str(ctx.get("reject_reason", "unknown"))
            if reason == "WATCHLIST":
                sc = compute_quality_score(
                    frame,
                    i,
                    int(resolve_candidate_direction(frame, i) or 0),
                    bar_open=pd.Timestamp(frame.index[i]),
                )
                rejections[f"watchlist_{sc.quality_score}"] += 1
            else:
                rejections[reason] += 1
            continue
        row = frame.iloc[i]
        signals.append({
            "bar_index": i,
            "bar_time": str(frame.index[i]),
            "direction": int(score.direction or 0),
            "entry": float(row["close"]),
            "sl_atr": 2.2,
            "rr": 1.6,
            "regime": ctx.get("regime"),
            "strategy_id": "QUALITY_ENGINE",
            "engine": "new",
            "quality_score": score.quality_score,
            "score_components": dict(score.score_components),
        })
    return signals, rejections


def _rejection_concentration(
    rejections: Counter[str],
    *,
    exclude_prefixes: tuple[str, ...] = ("NO_",),
    exclude_exact: tuple[str, ...] = ("no_signal",),
) -> float:
    filtered = Counter()
    for reason, count in rejections.items():
        if reason in exclude_exact:
            continue
        if any(reason.startswith(p) for p in exclude_prefixes):
            continue
        filtered[reason] = count
    total = sum(filtered.values())
    if total <= 0:
        return 0.0
    top = filtered.most_common(1)[0][1]
    return round(top / total * 100, 2)


def _score_distribution(frame: pd.DataFrame, *, warmup: int = 500) -> dict[str, int]:
    buckets: Counter[str] = Counter()
    for i in range(max(warmup, 60), len(frame)):
        direction = resolve_candidate_direction(frame, i)
        if direction is None:
            buckets["no_direction"] += 1
            continue
        sc = compute_quality_score(frame, i, direction, bar_open=pd.Timestamp(frame.index[i]))
        if sc.quality_score >= TRADEABLE_MIN:
            buckets["tradeable"] += 1
        elif sc.quality_score >= WATCHLIST_MIN:
            buckets["watchlist"] += 1
        else:
            buckets["reject"] += 1
    return dict(buckets)


def run_comparison(
    df: pd.DataFrame,
    *,
    warmup: int = 500,
) -> dict[str, Any]:
    frame = prepare_adaptive_frame(df)
    old_sigs, old_rej = _collect_old_signals(df, frame, warmup=warmup)
    new_sigs, new_rej = _collect_new_signals(df, frame, warmup=warmup)
    old_trades = _simulate_trades(df, frame, old_sigs)
    new_trades = _simulate_trades(df, frame, new_sigs)
    old_m = _metrics(old_trades)
    new_m = _metrics(new_trades)

    old_pf = _pf_num(old_m["pf"])
    new_pf = _pf_num(new_m["pf"])
    pf_uplift_pct = round((new_pf - old_pf) / old_pf * 100, 2) if old_pf > 0 else 0.0

    old_conc = _rejection_concentration(old_rej)
    new_conc = _rejection_concentration(new_rej)

    accepted = (
        new_pf > old_pf * 1.15
        and float(new_m["expectancy_r"]) > 0
        and float(new_m["max_dd_r"]) <= float(old_m["max_dd_r"])
        and new_conc < 40.0
    )

    return {
        "bars": len(df),
        "warmup": warmup,
        "old": {
            "signals": len(old_sigs),
            "metrics": old_m,
            "rejections": dict(old_rej),
            "rejection_concentration_pct": old_conc,
        },
        "new": {
            "signals": len(new_sigs),
            "metrics": new_m,
            "rejections": dict(new_rej),
            "rejection_concentration_pct": new_conc,
            "quality_rejection_concentration_pct": new_conc,
            "score_distribution": _score_distribution(frame, warmup=warmup),
        },
        "pf_uplift_pct": pf_uplift_pct,
        "quality_engine_accepted": accepted,
        "adaptive_production_ready": accepted,
    }
