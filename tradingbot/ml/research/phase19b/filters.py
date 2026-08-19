"""Phase 19B — candidate filter discovery (research only)."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from tradingbot.ml.phase19a.metrics import compute_performance


FilterFn = Callable[[dict[str, Any]], bool]


def _baseline(trades: list[dict]) -> dict[str, Any]:
    return compute_performance(trades)


def _apply(trades: list[dict], fn: FilterFn) -> list[dict]:
    return [t for t in trades if fn(t)]


def _eval_filter(name: str, trades: list[dict], fn: FilterFn, baseline: dict) -> dict[str, Any]:
    kept = _apply(trades, fn)
    perf = compute_performance(kept)
    removed = len(trades) - len(kept)
    winners_removed = sum(1 for t in trades if t.get("is_win") and not fn(t))
    losers_removed = sum(1 for t in trades if t.get("is_loss") and not fn(t))
    return {
        "name": name,
        "trades": perf["trades"],
        "trades_removed": removed,
        "losers_removed": losers_removed,
        "winners_removed": winners_removed,
        "profit_factor": perf["profit_factor"],
        "expectancy_r": perf["expectancy_r"],
        "maximum_drawdown_r": perf["maximum_drawdown_r"],
        "win_rate": perf["win_rate"],
        "net_profit_r": perf["net_profit_r"],
        "pf_delta": round(perf["profit_factor"] - baseline["profit_factor"], 4),
        "exp_delta": round(perf["expectancy_r"] - baseline["expectancy_r"], 4),
        "dd_delta": round(abs(perf["maximum_drawdown_r"]) - abs(baseline["maximum_drawdown_r"]), 4),
        "trade_retention": round(len(kept) / max(len(trades), 1), 4),
    }


def discover_filters(trades: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = _baseline(trades)
    candidates: list[tuple[str, FilterFn]] = []

    # ADX ranges
    for lo, hi in ((15, 50), (20, 45), (25, 60), (18, 40)):
        candidates.append((f"adx_{lo}_{hi}", lambda t, a=lo, b=hi: a <= float(t.get("adx", 0)) <= b))

    # ATR percentile / ATR
    atr_vals = [float(t.get("atr", 0)) for t in trades]
    if atr_vals:
        p25, p50, p75 = np.percentile(atr_vals, [25, 50, 75])
        candidates.append(("atr_below_p75", lambda t, x=p75: float(t.get("atr", 0)) <= x))
        candidates.append(("atr_above_p25", lambda t, x=p25: float(t.get("atr", 0)) >= x))
        candidates.append(("atr_mid", lambda t, a=p25, b=p75: a <= float(t.get("atr", 0)) <= b))

    # RSI zones
    candidates.append(("rsi_not_extreme", lambda t: 30 <= float(t.get("rsi", 50)) <= 70))
    candidates.append(("rsi_mid", lambda t: 40 <= float(t.get("rsi", 50)) <= 60))

    # Trend age
    candidates.append(("trend_age_ge_3", lambda t: float(t.get("trend_age", 0)) >= 3))
    candidates.append(("trend_age_ge_5", lambda t: float(t.get("trend_age", 0)) >= 5))
    candidates.append(("trend_age_le_50", lambda t: float(t.get("trend_age", 0)) <= 50))

    # Session
    for sess in ("LONDON", "NY", "ASIA"):
        candidates.append((f"session_{sess}", lambda t, s=sess: t.get("session") == s))
    candidates.append(("session_london_ny", lambda t: t.get("session") in ("LONDON", "NY")))

    # Hour bands
    candidates.append(("hour_8_20", lambda t: 8 <= int(t.get("hour", 0)) <= 20))
    candidates.append(("hour_avoid_0_4", lambda t: int(t.get("hour", 0)) not in (0, 1, 2, 3, 4)))

    # Spread
    spreads = [float(t.get("spread", 0)) for t in trades]
    if spreads:
        s75 = float(np.percentile(spreads, 75))
        candidates.append(("spread_below_p75", lambda t, x=s75: float(t.get("spread", 0)) <= x))

    # Confidence
    for thr in (0.35, 0.40, 0.45, 0.50, 0.55):
        candidates.append((f"confidence_ge_{thr}", lambda t, x=thr: float(t.get("confidence", 0)) >= x))

    # Quality
    for thr in (0.50, 0.55, 0.60, 0.65):
        candidates.append((f"quality_ge_{thr}", lambda t, x=thr: float(t.get("quality_score", 0)) >= x))

    # Risk score (lower risk_percent sometimes better)
    risks = [float(t.get("risk_percent", 0.005)) for t in trades]
    if risks:
        r50 = float(np.median(risks))
        candidates.append(("risk_le_median", lambda t, x=r50: float(t.get("risk_percent", 0)) <= x))

    # Regime focus
    candidates.append(("regime_range_only", lambda t: t.get("regime") == "RANGE"))
    candidates.append(("regime_trend_only", lambda t: t.get("regime") == "TREND"))

    # Duration
    candidates.append(("duration_ge_1", lambda t: int(t.get("duration_bars", 0)) >= 1))

    results = [_eval_filter(name, trades, fn, baseline) for name, fn in candidates]
    # Prefer PF up, expectancy up, DD down or flat, retain >= 40% trades, remove more losers than winners
    for r in results:
        score = (
            r["pf_delta"] * 10
            + r["exp_delta"] * 20
            - max(0, r["dd_delta"]) * 0.5
            + (r["losers_removed"] - r["winners_removed"]) * 0.02
        )
        r["research_score"] = round(score, 4)
        r["overfit_risk"] = (
            "HIGH" if r["trade_retention"] < 0.4 or r["trades"] < 20
            else ("MED" if r["trade_retention"] < 0.6 else "LOW")
        )

    results.sort(key=lambda x: -x["research_score"])

    # Combinations of top singles that improve PF
    top = [r for r in results if r["pf_delta"] > 0 and r["trade_retention"] >= 0.4][:8]
    name_to_fn = {n: f for n, f in candidates}
    combos = []
    for i, a in enumerate(top):
        for b in top[i + 1:]:
            fa, fb = name_to_fn[a["name"]], name_to_fn[b["name"]]
            combo_name = f"{a['name']}+{b['name']}"
            fn = lambda t, x=fa, y=fb: x(t) and y(t)
            combos.append(_eval_filter(combo_name, trades, fn, baseline))
    for r in combos:
        score = r["pf_delta"] * 10 + r["exp_delta"] * 20 - max(0, r["dd_delta"]) * 0.5
        r["research_score"] = round(score, 4)
        r["overfit_risk"] = (
            "HIGH" if r["trade_retention"] < 0.35 or r["trades"] < 15
            else ("MED" if r["trade_retention"] < 0.55 else "LOW")
        )
    combos.sort(key=lambda x: -x["research_score"])

    return {
        "phase": "19B",
        "baseline": baseline,
        "single_filters": results,
        "combinations": combos[:20],
        "ranked_candidates": (results[:10] + combos[:5]),
    }
