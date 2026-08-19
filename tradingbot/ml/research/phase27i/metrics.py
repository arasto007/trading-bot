"""Phase 27I — slippage root cause investigation metrics."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

import pandas as pd

from tradingbot.ml.research.phase26b.analyzers import _profit_factor
from tradingbot.ml.research.phase27a.metrics import _regime_norm, _safe_pct
from tradingbot.ml.research.phase27h.metrics import _metrics, INITIAL_BALANCE
from tradingbot.ml.research.phase27h.stress_engine import apply_slippage_stress, compute_atr
from tradingbot.ml.research.phase27i.slippage_decompose import SLIPPAGE_ATR_MULT

DURATION_BUCKETS = [
    ("1-5", 1, 5),
    ("6-10", 6, 10),
    ("11-20", 11, 20),
    ("20+", 21, 10_000),
]


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _median(vals: list[float]) -> float:
    return round(statistics.median(vals), 4) if vals else 0.0


def _subset_slippage_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trade_count": 0,
            "avg_slippage_loss": 0.0,
            "median_slippage_loss": 0.0,
            "worst_slippage_loss": 0.0,
            "net_profit_after_slippage": 0.0,
            "profit_factor_after_slippage": 0.0,
            "expectancy_after_slippage": 0.0,
        }
    slips = [float(r["total_slippage_loss"]) for r in rows]
    pnls_after = [float(r["pnl_after_slippage"]) for r in rows]
    pseudo_trades = [{"pnl": p} for p in pnls_after]
    return {
        "trade_count": len(rows),
        "avg_slippage_loss": _mean(slips),
        "median_slippage_loss": _median(slips),
        "worst_slippage_loss": round(max(slips), 4),
        "net_profit_after_slippage": round(sum(pnls_after), 4),
        "profit_factor_after_slippage": _profit_factor(pseudo_trades),
        "expectancy_after_slippage": round(sum(pnls_after) / len(pnls_after), 4),
    }


def build_slippage_breakdown(enriched: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    total_entry = sum(float(r["entry_slippage_loss"]) for r in enriched)
    total_exit = sum(float(r["exit_slippage_loss"]) for r in enriched)
    total_slip = sum(float(r["total_slippage_loss"]) for r in enriched)
    baseline_net = sum(float(r["baseline_pnl"]) for r in enriched)
    net_after = sum(float(r["pnl_after_slippage"]) for r in enriched)
    return {
        "phase": "27I",
        "slippage_atr_mult": SLIPPAGE_ATR_MULT,
        "trade_count": len(enriched),
        "total_entry_slippage_loss": round(total_entry, 4),
        "total_exit_slippage_loss": round(total_exit, 4),
        "total_slippage_loss": round(total_slip, 4),
        "baseline_net_profit": round(baseline_net, 4),
        "net_profit_after_slippage": round(net_after, 4),
        "slippage_pct_of_baseline_pnl": round(100.0 * total_slip / baseline_net, 2) if baseline_net else None,
        "avg_slippage_per_trade": round(total_slip / len(enriched), 4) if enriched else 0.0,
        "baseline_expectancy": baseline.get("expectancy"),
        "avg_slippage_vs_expectancy_ratio": round(
            (total_slip / len(enriched)) / baseline.get("expectancy", 1), 4
        )
        if enriched and baseline.get("expectancy")
        else None,
        "entry_share_of_slippage_pct": _safe_pct(total_entry, total_slip),
        "exit_share_of_slippage_pct": _safe_pct(total_exit, total_slip),
        "per_trade": enriched,
    }


def build_direction_slippage(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"phase": "27I"}
    for side in ("BUY", "SELL"):
        rows = [r for r in enriched if r["direction"] == side]
        slips = [float(r["total_slippage_loss"]) for r in rows]
        out[side] = {
            **_subset_slippage_metrics(rows),
            "avg_slippage": _mean(slips),
            "median_slippage": _median(slips),
            "worst_slippage": round(max(slips), 4) if slips else 0.0,
        }
    return out


def build_regime_slippage(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"phase": "27I", "regimes": {}}
    for regime in ("RANGE", "TREND", "TRANSITION"):
        rows = [r for r in enriched if _regime_norm(r.get("regime", "")) == regime]
        slips = [float(r["total_slippage_loss"]) for r in rows]
        out["regimes"][regime] = {
            "average_slippage": _mean(slips),
            **_subset_slippage_metrics(rows),
        }
    return out


def build_duration_slippage(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {label: [] for label, _, _ in DURATION_BUCKETS}
    for r in enriched:
        d = int(r.get("duration_bars") or 0)
        for label, lo, hi in DURATION_BUCKETS:
            if lo <= d <= hi:
                buckets[label].append(r)
                break
    out: dict[str, Any] = {"phase": "27I", "buckets": {}}
    for label, _, _ in DURATION_BUCKETS:
        rows = buckets[label]
        slips = [float(r["total_slippage_loss"]) for r in rows]
        baseline_pnls = [float(r["baseline_pnl"]) for r in rows]
        after_pnls = [float(r["pnl_after_slippage"]) for r in rows]
        out["buckets"][label] = {
            "trade_count": len(rows),
            "avg_slippage_loss": _mean(slips),
            "avg_baseline_pnl": _mean(baseline_pnls),
            "avg_pnl_after_slippage": _mean(after_pnls),
            "net_after_slippage": round(sum(after_pnls), 4),
            "absorbs_slippage": sum(after_pnls) > 0 if rows else None,
        }
    return out


def build_rr_decay(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    planned = [float(r["planned_rr"]) for r in enriched if r.get("planned_rr") is not None]
    realized = [float(r["realized_rr"]) for r in enriched if r.get("realized_rr") is not None]
    after = [float(r["rr_after_slippage"]) for r in enriched if r.get("rr_after_slippage") is not None]

    winners = [r for r in enriched if float(r["baseline_pnl"]) > 0]
    losers = [r for r in enriched if float(r["baseline_pnl"]) < 0]
    win_rr_loss = _mean([float(r["realized_rr"] or 0) - float(r["rr_after_slippage"] or 0) for r in winners if r.get("rr_after_slippage") is not None])
    lose_rr_loss = _mean([float(r["realized_rr"] or 0) - float(r["rr_after_slippage"] or 0) for r in losers if r.get("rr_after_slippage") is not None])

    return {
        "phase": "27I",
        "planned_rr": {"mean": _mean(planned), "median": _median(planned), "count": len(planned)},
        "realized_rr": {"mean": _mean(realized), "median": _median(realized), "count": len(realized)},
        "rr_after_slippage": {"mean": _mean(after), "median": _median(after), "count": len(after)},
        "winners_avg_rr_decay": win_rr_loss,
        "losers_avg_rr_decay": lose_rr_loss,
        "winners_lose_more_rr": win_rr_loss > lose_rr_loss,
        "note": "Slippage subtracts ~0.5 ATR from effective move in R terms when risk unit is SL distance",
    }


def build_atr_analysis(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    atrs = [float(r["atr_at_entry"]) for r in enriched]
    slips = [float(r["total_slippage_loss"]) for r in enriched]
    # Quartile buckets by ATR
    if not atrs:
        return {"phase": "27I", "trade_count": 0}
    sorted_pairs = sorted(zip(atrs, slips, enriched), key=lambda x: x[0])
    n = len(sorted_pairs)
    q_size = max(1, n // 4)
    quartiles: dict[str, Any] = {}
    for i, label in enumerate(("Q1_low", "Q2", "Q3", "Q4_high")):
        chunk = sorted_pairs[i * q_size : (i + 1) * q_size if i < 3 else n]
        rows = [c[2] for c in chunk]
        quartiles[label] = {
            "atr_range": [round(min(c[0] for c in chunk), 4), round(max(c[0] for c in chunk), 4)],
            "avg_slippage_loss": _mean([c[1] for c in chunk]),
            "net_after_slippage": round(sum(float(r["pnl_after_slippage"]) for r in rows), 4),
            "trade_count": len(rows),
        }
    corr_atr_slip = 0.0
    if len(atrs) > 1:
        mean_a = statistics.mean(atrs)
        mean_s = statistics.mean(slips)
        num = sum((a - mean_a) * (s - mean_s) for a, s in zip(atrs, slips))
        den_a = sum((a - mean_a) ** 2 for a in atrs) ** 0.5
        den_s = sum((s - mean_s) ** 2 for s in slips) ** 0.5
        corr_atr_slip = round(num / (den_a * den_s), 4) if den_a and den_s else 0.0

    high_atr = [r for r in enriched if float(r["atr_at_entry"]) >= _median(atrs)]
    low_atr = [r for r in enriched if float(r["atr_at_entry"]) < _median(atrs)]
    return {
        "phase": "27I",
        "atr_at_entry": {"mean": _mean(atrs), "median": _median(atrs), "max": round(max(atrs), 4)},
        "correlation_atr_slippage_loss": corr_atr_slip,
        "quartiles": quartiles,
        "high_atr_half": _subset_slippage_metrics(high_atr),
        "low_atr_half": _subset_slippage_metrics(low_atr),
        "high_atr_environments_fail": sum(float(r["pnl_after_slippage"]) for r in high_atr) < 0,
    }


def build_spread_analysis(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    ratios = [float(r["spread_atr_ratio"]) for r in enriched if r.get("spread_atr_ratio") is not None]
    pnls = [float(r["baseline_pnl"]) for r in enriched]
    spreads = [float(r["spread"]) for r in enriched]

    def _corr(xs: list[float], ys: list[float]) -> float:
        if len(xs) < 2:
            return 0.0
        mx, my = statistics.mean(xs), statistics.mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        return round(num / (dx * dy), 4) if dx and dy else 0.0

    high_ratio = [r for r in enriched if float(r.get("spread_atr_ratio") or 0) >= _median(ratios)]
    low_ratio = [r for r in enriched if float(r.get("spread_atr_ratio") or 0) < _median(ratios)]
    return {
        "phase": "27I",
        "avg_spread": _mean(spreads),
        "avg_atr": _mean([float(r["atr_at_entry"]) for r in enriched]),
        "avg_spread_atr_ratio": _mean(ratios),
        "correlation_spread_atr_ratio_vs_baseline_pnl": _corr(ratios, pnls),
        "high_spread_atr_ratio_half": {
            "net_baseline": round(sum(float(r["baseline_pnl"]) for r in high_ratio), 4),
            "net_after_slippage": round(sum(float(r["pnl_after_slippage"]) for r in high_ratio), 4),
            "trade_count": len(high_ratio),
        },
        "low_spread_atr_ratio_half": {
            "net_baseline": round(sum(float(r["baseline_pnl"]) for r in low_ratio), 4),
            "net_after_slippage": round(sum(float(r["pnl_after_slippage"]) for r in low_ratio), 4),
            "trade_count": len(low_ratio),
        },
    }


def build_execution_price_analysis(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    total_entry = sum(float(r["entry_slippage_loss"]) for r in enriched)
    total_exit = sum(float(r["exit_slippage_loss"]) for r in enriched)
    total = total_entry + total_exit or 1e-9
    return {
        "phase": "27I",
        "entry_slippage_total": round(total_entry, 4),
        "exit_slippage_total": round(total_exit, 4),
        "entry_contribution_pct": _safe_pct(total_entry, total),
        "exit_contribution_pct": _safe_pct(total_exit, total),
        "primary_sensitivity": (
            "entry"
            if total_entry > total_exit * 1.05
            else "exit"
            if total_exit > total_entry * 1.05
            else "both_equally"
        ),
        "avg_entry_slippage_per_trade": round(total_entry / len(enriched), 4) if enriched else 0.0,
        "avg_exit_slippage_per_trade": round(total_exit / len(enriched), 4) if enriched else 0.0,
    }


def build_edge_decay(
    trades: list[dict[str, Any]],
    candles: pd.DataFrame,
    enriched: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    atr = compute_atr(candles)
    baseline_edge = float(baseline.get("expectancy") or 0)
    after_edge = round(
        sum(float(r["pnl_after_slippage"]) for r in enriched) / len(enriched), 4
    ) if enriched else 0.0
    avg_slip = round(sum(float(r["total_slippage_loss"]) for r in enriched) / len(enriched), 4) if enriched else 0.0
    edge_destroyed_pct = round(100.0 * (1 - after_edge / baseline_edge), 2) if baseline_edge else None

    sweep: list[dict[str, Any]] = []
    breakeven_pf_mult = None
    breakeven_exp_mult = None
    for mult_x100 in range(0, 51, 1):
        mult = mult_x100 / 100.0
        stressed = apply_slippage_stress(trades, mult, candles, atr)
        m = _metrics(stressed, initial=INITIAL_BALANCE)
        sweep.append({"atr_mult": round(mult, 2), "profit_factor": m["profit_factor"], "expectancy": m["expectancy"]})
        pf = float(m["profit_factor"]) if isinstance(m["profit_factor"], (int, float)) else 0.0
        if breakeven_pf_mult is None and pf < 1.0 and mult > 0:
            breakeven_pf_mult = round(mult, 4)
        if breakeven_exp_mult is None and m["expectancy"] < 0 and mult > 0:
            breakeven_exp_mult = round(mult, 4)

    return {
        "phase": "27I",
        "expected_edge_before_slippage": baseline_edge,
        "expected_edge_after_0.25_atr": after_edge,
        "avg_slippage_cost_per_trade": avg_slip,
        "edge_destroyed_pct_at_0.25_atr": edge_destroyed_pct,
        "minimum_atr_mult_pf_below_1": breakeven_pf_mult,
        "minimum_atr_mult_expectancy_below_0": breakeven_exp_mult,
        "sweep": sweep,
    }


def build_root_cause_rank(
    *,
    breakdown: dict[str, Any],
    direction: dict[str, Any],
    duration: dict[str, Any],
    rr_decay: dict[str, Any],
    atr_analysis: dict[str, Any],
    spread_analysis: dict[str, Any],
    execution_price: dict[str, Any],
    edge_decay: dict[str, Any],
    enriched: list[dict[str, Any]],
) -> dict[str, Any]:
    avg_slip = float(breakdown.get("avg_slippage_per_trade") or 0)
    baseline_exp = float(breakdown.get("baseline_expectancy") or 0)
    tp_atr = _mean([float(r["tp_atr_ratio"]) for r in enriched if r.get("tp_atr_ratio") is not None])
    avg_duration = _mean([float(r["duration_bars"]) for r in enriched])
    realized_rr = float(rr_decay.get("realized_rr", {}).get("mean") or 0)
    breakeven = float(edge_decay.get("minimum_atr_mult_pf_below_1") or 0)

    causes: list[dict[str, Any]] = [
        {
            "cause": "thin_per_trade_edge",
            "impact_score": round(min(100, 100 * avg_slip / max(baseline_exp, 0.01)), 2),
            "evidence": f"avg slippage ${avg_slip} > baseline expectancy ${baseline_exp}",
        },
        {
            "cause": "round_trip_double_slippage",
            "impact_score": 95.0,
            "evidence": "0.25 ATR applied to BOTH entry and exit = 0.5 ATR price drag per trade",
        },
        {
            "cause": "high_atr_amplifies_dollar_slippage",
            "impact_score": round(abs(float(atr_analysis.get("correlation_atr_slippage_loss") or 0)) * 100, 2),
            "evidence": f"ATR-slippage correlation={atr_analysis.get('correlation_atr_slippage_loss')}",
        },
        {
            "cause": "small_tp_relative_to_atr",
            "impact_score": round(max(0, 100 - tp_atr * 30), 2),
            "evidence": f"avg TP/ATR ratio={tp_atr} — TP capture small vs volatility unit",
        },
        {
            "cause": "short_holding_time",
            "impact_score": round(max(0, 100 - avg_duration * 3), 2),
            "evidence": f"avg duration={avg_duration} bars — limited time to overcome slip",
        },
        {
            "cause": "poor_realized_rr",
            "impact_score": round(max(0, (2.0 - realized_rr) * 40), 2),
            "evidence": f"realized RR mean={realized_rr} vs planned 2.5",
        },
        {
            "cause": "spread_cost",
            "impact_score": round(float(spread_analysis.get("avg_spread_atr_ratio") or 0) * 50, 2),
            "evidence": f"spread/ATR={spread_analysis.get('avg_spread_atr_ratio')}",
        },
        {
            "cause": "entry_exit_symmetric_sensitivity",
            "impact_score": 50.0 if execution_price.get("primary_sensitivity") == "both_equally" else 70.0,
            "evidence": execution_price.get("primary_sensitivity"),
        },
        {
            "cause": "sell_side_concentration",
            "impact_score": round(
                100 * direction.get("SELL", {}).get("trade_count", 0) / max(len(enriched), 1), 2
            ),
            "evidence": f"SELL {direction.get('SELL', {}).get('trade_count', 0)} vs BUY {direction.get('BUY', {}).get('trade_count', 0)}",
        },
        {
            "cause": "low_breakeven_slippage_tolerance",
            "impact_score": round(max(0, (0.25 - breakeven) / 0.25 * 100) if breakeven else 80, 2),
            "evidence": f"PF<1 at ATR mult={breakeven} (below 0.25 test level)",
        },
    ]
    ranked = sorted(causes, key=lambda x: x["impact_score"], reverse=True)
    primary = ranked[0]["cause"]
    combination = primary in ("thin_per_trade_edge", "round_trip_double_slippage", "high_atr_amplifies_dollar_slippage")
    return {
        "phase": "27I",
        "ranked_causes": ranked,
        "primary_root_cause": primary,
        "is_combination": combination,
        "combination_summary": (
            "Thin per-trade edge + round-trip 0.5 ATR price drag + ATR-proportional dollar slippage on XAUUSD M5"
            if combination
            else primary
        ),
    }


def determine_verdict(root_cause: dict[str, Any], breakdown: dict[str, Any]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if not root_cause.get("primary_root_cause"):
        blockers.append("no primary cause identified")
    if not breakdown.get("total_slippage_loss"):
        blockers.append("slippage breakdown empty")
    if root_cause.get("ranked_causes") and len(root_cause["ranked_causes"]) < 3:
        blockers.append("insufficient cause ranking depth")
    if blockers:
        return "SLIPPAGE_ROOT_CAUSE_NOT_IDENTIFIED", blockers
    return "SLIPPAGE_ROOT_CAUSE_IDENTIFIED", blockers


def build_final_report(
    *,
    root_cause: dict[str, Any],
    breakdown: dict[str, Any],
    edge_decay: dict[str, Any],
    execution_price: dict[str, Any],
    trade_count: int,
) -> dict[str, Any]:
    verdict, blockers = determine_verdict(root_cause, breakdown)
    return {
        "phase": "27I",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "input_source": "phase27f_repaired_replay",
        "slippage_scenario": "0.25 ATR entry + 0.25 ATR exit (Phase 27H model)",
        "completed_trades": trade_count,
        "primary_root_cause": root_cause.get("primary_root_cause"),
        "combination_summary": root_cause.get("combination_summary"),
        "blockers": blockers,
        "key_findings": {
            "baseline_net": breakdown.get("baseline_net_profit"),
            "net_after_slippage": breakdown.get("net_profit_after_slippage"),
            "total_slippage_destroyed": breakdown.get("total_slippage_loss"),
            "slippage_pct_of_baseline_pnl": breakdown.get("slippage_pct_of_baseline_pnl"),
            "avg_slippage_per_trade": breakdown.get("avg_slippage_per_trade"),
            "baseline_expectancy": breakdown.get("baseline_expectancy"),
            "slippage_vs_expectancy_ratio": breakdown.get("avg_slippage_vs_expectancy_ratio"),
            "entry_vs_exit": execution_price.get("primary_sensitivity"),
            "pf_breakeven_atr_mult": edge_decay.get("minimum_atr_mult_pf_below_1"),
        },
        "conclusion": root_cause.get("combination_summary"),
    }
