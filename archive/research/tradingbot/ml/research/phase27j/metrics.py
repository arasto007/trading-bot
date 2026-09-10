"""Phase 27J — edge decomposition investigation metrics."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from tradingbot.ml.research.phase26b.analyzers import _histogram, _profit_factor
from tradingbot.ml.research.phase27a.metrics import _regime_norm, _safe_pct


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _median(vals: list[float]) -> float:
    return round(statistics.median(vals), 4) if vals else 0.0


def build_edge_per_trade(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "gross_edge": sum(float(r["gross_edge"]) for r in enriched),
        "spread_cost": sum(float(r["spread_cost"]) for r in enriched),
        "commission": sum(float(r["commission"]) for r in enriched),
        "swap": sum(float(r["swap"]) for r in enriched),
        "slippage_cost": sum(float(r["slippage_cost"]) for r in enriched),
        "net_edge": sum(float(r["net_edge"]) for r in enriched),
        "net_after_slippage": sum(float(r["net_after_slippage"]) for r in enriched),
    }
    n = len(enriched) or 1
    return {
        "phase": "27J",
        "trade_count": len(enriched),
        "totals": {k: round(v, 4) for k, v in totals.items()},
        "averages": {k: round(v / n, 4) for k, v in totals.items()},
        "trades": enriched,
    }


def build_winner_analysis(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    winners = [r for r in enriched if float(r["baseline_pnl"]) > 0]
    gross_moves = [float(r["mfe_price"]) for r in winners]
    captured = [float(r["captured_move_price"]) for r in winners]
    capture_ratios = [float(r["capture_efficiency"]) for r in winners if r.get("capture_efficiency") is not None]
    tp_dists = [float(r["tp_distance"]) for r in winners if r.get("tp_distance") is not None]
    exit_prices = [float(r["captured_move_price"]) for r in winners]
    unused_r = [float(r["missed_opportunity_r"]) for r in winners]
    avg_capture = _mean(capture_ratios)
    return {
        "phase": "27J",
        "winner_count": len(winners),
        "average_gross_move_price": _mean(gross_moves),
        "average_captured_move_price": _mean(captured),
        "capture_ratio_mean": avg_capture,
        "capture_ratio_median": _median(capture_ratios),
        "average_planned_tp_distance": _mean(tp_dists),
        "average_actual_exit_move_price": _mean(exit_prices),
        "average_unused_remaining_move_r": _mean(unused_r),
        "average_winner_final_r": _mean([float(r["final_r"]) for r in winners]),
        "exited_too_early": avg_capture < 0.65 if capture_ratios else None,
        "note": "capture_ratio = final_r / mfe_r; values << 1 indicate early exit vs available move",
    }


def build_loser_analysis(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    losers = [r for r in enriched if float(r["baseline_pnl"]) < 0]
    mae = [float(r["mae_r"]) for r in losers]
    sl_dist = [float(r["sl_distance"]) for r in losers if r.get("sl_distance")]
    buffer = [float(r["sl_buffer_remaining_r"]) for r in losers if r.get("sl_buffer_remaining_r") is not None]
    sl_exits = [r for r in losers if r.get("exit_reason") == "sl"]
    return {
        "phase": "27J",
        "loser_count": len(losers),
        "average_mae_r": _mean(mae),
        "average_sl_distance_price": _mean(sl_dist),
        "average_sl_buffer_remaining_r": _mean(buffer),
        "sl_exit_count": len(sl_exits),
        "sl_exit_pct": _safe_pct(len(sl_exits), len(losers)),
        "losses_larger_than_1r": sum(1 for r in losers if float(r["final_r"]) < -1.0),
        "average_loser_final_r": _mean([float(r["final_r"]) for r in losers]),
        "losses_larger_than_necessary": _mean(mae) > 0.85,
    }


def build_capture_efficiency(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    eff = [float(r["capture_efficiency"]) for r in enriched if r.get("capture_efficiency") is not None]
    missed = [float(r["missed_opportunity_r"]) for r in enriched]
    mfe = [float(r["mfe_r"]) for r in enriched]
    captured_r = [float(r["captured_r"]) for r in enriched]
    return {
        "phase": "27J",
        "trade_count": len(enriched),
        "average_mfe_r": _mean(mfe),
        "average_captured_r": _mean(captured_r),
        "average_capture_efficiency": _mean(eff),
        "median_capture_efficiency": _median(eff),
        "average_missed_opportunity_r": _mean(missed),
        "capture_efficiency_distribution": _histogram(eff, bins=10),
        "missed_opportunity_distribution": _histogram(missed, bins=10),
    }


def build_exit_quality(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in enriched:
        reason = str(r.get("exit_reason") or "unknown").upper()
        if reason == "SL":
            key = "SL"
        elif reason == "TP":
            key = "TP"
        elif reason == "TIMEOUT":
            key = "TIMEOUT"
        else:
            key = "Manual"
        groups[key].append(r)

    out: dict[str, Any] = {"phase": "27J", "by_exit_type": {}}
    for key in ("TP", "SL", "TIMEOUT", "Manual"):
        rows = groups.get(key, [])
        pnls = [float(r["baseline_pnl"]) for r in rows]
        missed = [float(r["missed_opportunity_r"]) for r in rows]
        eff = [float(r["capture_efficiency"]) for r in rows if r.get("capture_efficiency") is not None]
        out["by_exit_type"][key] = {
            "count": len(rows),
            "average_profit": _mean(pnls),
            "average_missed_move_r": _mean(missed),
            "average_efficiency": _mean(eff),
            "profit_factor": _profit_factor([{"pnl": p} for p in pnls]) if rows else 0.0,
        }
    return out


def _bucket_expectancy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0, "net_edge": 0.0, "expectancy": 0.0}
    net = sum(float(r["net_edge"]) for r in rows)
    return {"count": len(rows), "net_edge": round(net, 4), "expectancy": round(net / len(rows), 4)}


def build_edge_sources(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    total_net = sum(float(r["net_edge"]) for r in enriched) or 1e-9

    by_direction: dict[str, Any] = {}
    for d in ("BUY", "SELL"):
        rows = [r for r in enriched if r["direction"] == d]
        by_direction[d] = _bucket_expectancy(rows)

    by_regime: dict[str, Any] = {}
    for regime in ("RANGE", "TREND", "TRANSITION"):
        rows = [r for r in enriched if _regime_norm(r.get("regime", "")) == regime]
        by_regime[regime] = _bucket_expectancy(rows)

    high_conf = [r for r in enriched if float(r["confidence"]) >= 0.90]
    low_conf = [r for r in enriched if float(r["confidence"]) < 0.90]

    tp_exits = [r for r in enriched if r.get("exit_reason") == "tp"]
    sl_exits = [r for r in enriched if r.get("exit_reason") == "sl"]
    timeout_exits = [r for r in enriched if r.get("exit_reason") == "timeout"]

    contributions = {
        "entry_direction_sell": by_direction.get("SELL", {}),
        "entry_direction_buy": by_direction.get("BUY", {}),
        "exit_tp_quality": _bucket_expectancy(tp_exits),
        "exit_sl_quality": _bucket_expectancy(sl_exits),
        "exit_timeout_quality": _bucket_expectancy(timeout_exits),
        "regime_range": by_regime.get("RANGE", {}),
        "confidence_high_gte_0.90": _bucket_expectancy(high_conf),
        "confidence_low_lt_0.90": _bucket_expectancy(low_conf),
        "risk_sizing_avg_lot": _mean([float(r["lot"]) for r in enriched]),
    }

    ranked = sorted(
        [
            ("SELL_direction", by_direction.get("SELL", {}).get("net_edge", 0)),
            ("high_confidence", _bucket_expectancy(high_conf).get("net_edge", 0)),
            ("TP_exits", _bucket_expectancy(tp_exits).get("net_edge", 0)),
            ("RANGE_regime", by_regime.get("RANGE", {}).get("net_edge", 0)),
            ("TIMEOUT_exits", _bucket_expectancy(timeout_exits).get("net_edge", 0)),
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    return {
        "phase": "27J",
        "total_net_edge": round(total_net, 4),
        "contributions": contributions,
        "largest_contributors_ranked": [{"source": k, "net_edge": v} for k, v in ranked],
        "primary_edge_source": ranked[0][0] if ranked else None,
    }


def build_r_multiple_analysis(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    final_r = [float(r["final_r"]) for r in enriched]
    planned = [float(r["planned_rr"]) for r in enriched if r.get("planned_rr") is not None]
    winners = [float(r["final_r"]) for r in enriched if float(r["baseline_pnl"]) > 0]
    losers = [float(r["final_r"]) for r in enriched if float(r["baseline_pnl"]) < 0]
    initial_risk = [float(r["initial_risk_dollars"]) for r in enriched if r.get("initial_risk_dollars")]
    return {
        "phase": "27J",
        "average_initial_risk_dollars": _mean(initial_risk),
        "final_r_distribution": _histogram(final_r, bins=12),
        "average_final_r": _mean(final_r),
        "median_final_r": _median(final_r),
        "average_winner_r": _mean(winners),
        "average_loser_r": _mean(losers),
        "planned_rr_mean": _mean(planned),
        "planned_vs_realized_gap": round(_mean(planned) - _mean(final_r), 4) if planned else None,
        "realized_below_planned": _mean(final_r) < _mean(planned) if planned else None,
    }


def build_opportunity_loss(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    tp_rows = [r for r in enriched if r.get("exit_reason") == "tp"]
    timeout_rows = [r for r in enriched if r.get("exit_reason") == "timeout"]
    sl_rows = [r for r in enriched if r.get("exit_reason") == "sl"]

    return {
        "phase": "27J",
        "average_profit_left_after_exit_r": _mean([float(r["post_exit_opportunity_r"]) for r in enriched]),
        "after_tp_remaining_move_r": _mean([float(r["post_exit_opportunity_r"]) for r in tp_rows]),
        "after_timeout_remaining_move_r": _mean([float(r["post_exit_opportunity_r"]) for r in timeout_rows]),
        "after_sl_post_exit_favorable_r": _mean([float(r["post_exit_opportunity_r"]) for r in sl_rows]),
        "in_trade_missed_r": _mean([float(r["missed_opportunity_r"]) for r in enriched]),
        "exit_timing_loss_dollars_total": round(sum(float(r["exit_timing_loss_dollars"]) for r in enriched), 4),
        "note": "post_exit measures favorable move in next 72 bars after exit",
    }


def build_edge_decay(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    gross_total = sum(float(r["gross_edge"]) for r in enriched) or 1e-9
    components = {
        "spread": sum(float(r["spread_cost"]) for r in enriched),
        "commission": sum(float(r["commission"]) for r in enriched),
        "swap": sum(float(r["swap"]) for r in enriched),
        "slippage": sum(float(r["slippage_cost"]) for r in enriched),
        "exit_timing": sum(float(r["exit_timing_loss_dollars"]) for r in enriched),
        "missed_move": sum(
            float(r["missed_opportunity_r"]) * float(r["initial_risk_dollars"] or 0) for r in enriched
        ),
    }
    pct = {k: round(100.0 * v / gross_total, 2) for k, v in components.items()}
    net_total = sum(float(r["net_edge"]) for r in enriched)
    return {
        "phase": "27J",
        "gross_edge_total": round(gross_total, 4),
        "net_edge_total": round(net_total, 4),
        "edge_lost_dollars": components,
        "edge_lost_pct_of_gross": pct,
        "largest_decay_factor": max(pct.items(), key=lambda x: x[1])[0] if pct else None,
    }


def build_root_cause_rank(
    *,
    winner: dict[str, Any],
    loser: dict[str, Any],
    capture: dict[str, Any],
    exit_q: dict[str, Any],
    edge_decay: dict[str, Any],
    r_mult: dict[str, Any],
    opportunity: dict[str, Any],
    enriched: list[dict[str, Any]],
) -> dict[str, Any]:
    avg_duration = _mean([float(r["duration_bars"]) for r in enriched])
    avg_winner_r = float(winner.get("average_winner_final_r") or 0)
    planned_rr = float(r_mult.get("planned_rr_mean") or 2.5)
    capture_eff = float(capture.get("average_capture_efficiency") or 0)
    decay_pcts = edge_decay.get("edge_lost_pct_of_gross") or {}

    causes = [
        {
            "cause": "small_winners_low_realized_r",
            "impact_score": round(max(0, (planned_rr - avg_winner_r) / planned_rr * 100), 2),
            "evidence": f"avg winner R={avg_winner_r} vs planned {planned_rr}",
        },
        {
            "cause": "poor_capture_efficiency",
            "impact_score": round(max(0, (1 - capture_eff) * 100), 2),
            "evidence": f"capture efficiency={capture_eff}",
        },
        {
            "cause": "large_loser_count",
            "impact_score": round(_safe_pct(loser.get("loser_count", 0), len(enriched)), 2),
            "evidence": f"{loser.get('loser_count')} losers vs {winner.get('winner_count')} winners",
        },
        {
            "cause": "execution_costs_spread_commission",
            "impact_score": decay_pcts.get("spread", 0) + decay_pcts.get("commission", 0),
            "evidence": f"spread={decay_pcts.get('spread')}% commission={decay_pcts.get('commission')}%",
        },
        {
            "cause": "hypothetical_slippage_drag",
            "impact_score": decay_pcts.get("slippage", 0),
            "evidence": f"slippage={decay_pcts.get('slippage')}% of gross",
        },
        {
            "cause": "missed_move_exit_timing",
            "impact_score": decay_pcts.get("missed_move", 0) + decay_pcts.get("exit_timing", 0),
            "evidence": f"missed_move={decay_pcts.get('missed_move')}% exit_timing={decay_pcts.get('exit_timing')}%",
        },
        {
            "cause": "timeout_exits_underperform",
            "impact_score": round(
                max(
                    0,
                    -float((exit_q.get("by_exit_type") or {}).get("TIMEOUT", {}).get("average_profit", 0)) * 10,
                ),
                2,
            ),
            "evidence": str((exit_q.get("by_exit_type") or {}).get("TIMEOUT", {})),
        },
        {
            "cause": "short_holding_time",
            "impact_score": round(max(0, 100 - avg_duration * 2), 2),
            "evidence": f"avg duration={avg_duration} bars",
        },
        {
            "cause": "post_exit_opportunity_left",
            "impact_score": round(float(opportunity.get("average_profit_left_after_exit_r") or 0) * 20, 2),
            "evidence": f"post-exit favorable R={opportunity.get('average_profit_left_after_exit_r')}",
        },
    ]
    ranked = sorted(causes, key=lambda x: x["impact_score"], reverse=True)
    return {
        "phase": "27J",
        "ranked_causes": ranked,
        "primary_root_cause": ranked[0]["cause"] if ranked else None,
        "combination_summary": (
            f"{ranked[0]['cause']} + {ranked[1]['cause']}" if len(ranked) >= 2 else ranked[0]["cause"] if ranked else ""
        ),
    }


def determine_verdict(root_cause: dict[str, Any], enriched: list[dict[str, Any]]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if not enriched:
        blockers.append("no trades enriched")
    if not root_cause.get("primary_root_cause"):
        blockers.append("no primary root cause")
    if len(root_cause.get("ranked_causes") or []) < 5:
        blockers.append("insufficient cause ranking")
    if blockers:
        return "EDGE_ROOT_CAUSE_NOT_IDENTIFIED", blockers
    return "EDGE_ROOT_CAUSE_IDENTIFIED", blockers


def build_final_report(
    *,
    root_cause: dict[str, Any],
    edge_per_trade: dict[str, Any],
    winner: dict[str, Any],
    loser: dict[str, Any],
    edge_decay: dict[str, Any],
    r_mult: dict[str, Any],
    capture: dict[str, Any],
    trade_count: int,
) -> dict[str, Any]:
    verdict, blockers = determine_verdict(root_cause, edge_per_trade.get("trades") or [])
    avgs = edge_per_trade.get("averages") or {}
    return {
        "phase": "27J",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "input_source": "phase27f_repaired_replay",
        "completed_trades": trade_count,
        "primary_root_cause": root_cause.get("primary_root_cause"),
        "combination_summary": root_cause.get("combination_summary"),
        "blockers": blockers,
        "key_findings": {
            "avg_gross_edge": avgs.get("gross_edge"),
            "avg_net_edge": avgs.get("net_edge"),
            "avg_spread_cost": avgs.get("spread_cost"),
            "avg_slippage_cost": avgs.get("slippage_cost"),
            "avg_winner_r": winner.get("average_winner_final_r"),
            "avg_loser_r": loser.get("average_loser_final_r"),
            "planned_rr": r_mult.get("planned_rr_mean"),
            "capture_efficiency": capture.get("average_capture_efficiency"),
            "exited_too_early": winner.get("exited_too_early"),
            "largest_edge_destroyer": edge_decay.get("largest_decay_factor"),
        },
        "conclusion": root_cause.get("combination_summary"),
    }
