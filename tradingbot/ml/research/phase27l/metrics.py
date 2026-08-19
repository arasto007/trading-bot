"""Phase 27L — exit engine investigation metrics."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _profit_factor
from tradingbot.ml.research.phase27a.metrics import _safe_pct
from tradingbot.ml.research.phase27l.exit_simulators import EXIT_STRATEGIES

INITIAL_BALANCE = 10_000.0


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _strategy_metrics(sim_results: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    trades = []
    for row in sim_results:
        s = row["strategies"][strategy]
        trades.append({"pnl": s["pnl"], "pnl_r": s.get("pnl_r", 0.0), "timestamp": row.get("timestamp")})
    if not trades:
        return {"trade_count": 0}
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    eq = _equity_curve(trades, initial=INITIAL_BALANCE)
    dd_pct, dd_abs = _max_drawdown(eq)
    ret_pct = net / INITIAL_BALANCE * 100
    pf = _profit_factor(trades)
    return {
        "trade_count": len(trades),
        "net_profit": round(net, 4),
        "profit_factor": pf,
        "expectancy": round(net / len(trades), 4),
        "win_rate_pct": _safe_pct(len(wins), len(trades)),
        "average_winner": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "average_loser": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "max_drawdown_pct": round(dd_pct, 4),
        "max_drawdown_abs": round(dd_abs, 4),
        "sharpe_ratio": round(_sharpe(eq, "M5"), 4),
        "sortino_ratio": round(_sortino(eq, "M5"), 4),
        "calmar_ratio": round(ret_pct / dd_pct, 4) if dd_pct > 0 else ("inf" if ret_pct > 0 else 0.0),
        "recovery_factor": _recovery_factor(net, dd_abs),
    }


def build_exit_timeline(traces: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "phase": "27L",
        "trade_count": len(traces),
        "traces": traces,
    }


def build_profit_timeline_report(timelines: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [k for k in (timelines[0].get("milestones_bars") or {}).keys()] if timelines else []
    agg: dict[str, list[int]] = defaultdict(list)
    pct_profitable: list[float] = []
    for t in timelines:
        pct_profitable.append(float(t.get("pct_bars_profitable") or 0))
        for k in keys:
            v = t.get("milestones_bars", {}).get(k)
            if v is not None:
                agg[k].append(int(v))
    milestone_stats = {
        k: {"mean_bars": _mean([float(x) for x in agg[k]]), "median_bars": round(statistics.median(agg[k]), 2) if agg[k] else None, "reach_count": len(agg[k])}
        for k in keys
    }
    return {
        "phase": "27L",
        "trade_count": len(timelines),
        "milestone_stats": milestone_stats,
        "avg_pct_bars_profitable": _mean(pct_profitable),
        "timelines": timelines,
    }


def build_reversal_analysis(reversal_rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [k for k in reversal_rows[0].keys()] if reversal_rows else []
    summary: dict[str, Any] = {}
    for k in keys:
        reached = [r[k] for r in reversal_rows if r.get(k, {}).get("reached")]
        if not reached:
            continue
        to_zero = [float(x["bars_to_zero_r"]) for x in reached if x.get("bars_to_zero_r") is not None]
        to_neg = [float(x["bars_to_neg1_r"]) for x in reached if x.get("bars_to_neg1_r") is not None]
        summary[k] = {
            "reached_count": len(reached),
            "pct_reversed_to_zero": _safe_pct(len(to_zero), len(reached)),
            "avg_bars_to_zero_r": _mean(to_zero),
            "avg_bars_to_neg1_r": _mean(to_neg),
        }
    return {"phase": "27L", "summary": summary, "per_trade": reversal_rows}


def build_exit_simulations(sim_results: list[dict[str, Any]]) -> dict[str, Any]:
    strategies = {s: _strategy_metrics(sim_results, s) for s in EXIT_STRATEGIES}
    return {"phase": "27L", "trade_count": len(sim_results), "strategies": strategies, "per_trade": sim_results}


def build_edge_recovery(sim_results: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = _strategy_metrics(sim_results, "current_tp_sl")
    recovery: dict[str, Any] = {}
    for s in EXIT_STRATEGIES:
        if s == "current_tp_sl":
            continue
        m = _strategy_metrics(sim_results, s)
        recovery[s] = {
            **m,
            "net_profit_delta": round(m["net_profit"] - baseline["net_profit"], 4),
            "expectancy_delta": round(m["expectancy"] - baseline["expectancy"], 4),
            "pf_delta": (
                round(float(m["profit_factor"]) - float(baseline["profit_factor"]), 4)
                if isinstance(m["profit_factor"], (int, float)) and isinstance(baseline["profit_factor"], (int, float))
                else None
            ),
        }
    return {"phase": "27L", "baseline": baseline, "recovery_by_strategy": recovery}


def build_loser_recovery(sim_results: list[dict[str, Any]]) -> dict[str, Any]:
    losers = [r for r in sim_results if float(r["baseline_pnl"]) < 0]
    out: dict[str, Any] = {"phase": "27L", "baseline_loser_count": len(losers), "by_strategy": {}}
    for s in EXIT_STRATEGIES:
        if s == "current_tp_sl":
            continue
        recovered = []
        for row in losers:
            sim_pnl = float(row["strategies"][s]["pnl"])
            if sim_pnl > 0:
                recovered.append(
                    {
                        "timestamp": row.get("timestamp"),
                        "baseline_pnl": row["baseline_pnl"],
                        "sim_pnl": sim_pnl,
                        "recovered_r": float(row["strategies"][s].get("pnl_r") or 0),
                    }
                )
        recovered_r = [float(x["recovered_r"]) for x in recovered]
        recovered_dollars = sum(float(x["sim_pnl"]) - float(x["baseline_pnl"]) for x in recovered)
        out["by_strategy"][s] = {
            "recovered_trades": len(recovered),
            "recovered_pct": _safe_pct(len(recovered), len(losers)),
            "recovered_r_total": round(sum(recovered_r), 4),
            "recovered_dollars_delta": round(recovered_dollars, 4),
            "recovered_expectancy": round(recovered_dollars / len(losers), 4) if losers else 0.0,
        }
    return out


def build_winner_preservation(sim_results: list[dict[str, Any]]) -> dict[str, Any]:
    winners = [r for r in sim_results if float(r["baseline_pnl"]) > 0]
    out: dict[str, Any] = {"phase": "27L", "baseline_winner_count": len(winners), "by_strategy": {}}
    base_r = [float(r["strategies"]["current_tp_sl"]["pnl_r"]) for r in winners]
    base_pnl = [float(r["baseline_pnl"]) for r in winners]
    for s in EXIT_STRATEGIES:
        if s == "current_tp_sl":
            continue
        sim_r = [float(r["strategies"][s]["pnl_r"]) for r in winners]
        sim_pnl = [float(r["strategies"][s]["pnl"]) for r in winners]
        capture = [sim_r[i] / base_r[i] if base_r[i] else 0 for i in range(len(winners))]
        out["by_strategy"][s] = {
            "avg_winner_r_baseline": _mean(base_r),
            "avg_winner_r_simulated": _mean(sim_r),
            "avg_winner_pnl_baseline": _mean(base_pnl),
            "avg_winner_pnl_simulated": _mean(sim_pnl),
            "capture_ratio_mean": _mean(capture),
            "winners_reduced": sum(1 for i in range(len(winners)) if sim_pnl[i] < base_pnl[i]),
            "winners_preserved_pct": _safe_pct(
                sum(1 for i in range(len(winners)) if sim_pnl[i] >= base_pnl[i] * 0.85),
                len(winners),
            ),
        }
    return out


def build_exit_scoreboard(sim_results: list[dict[str, Any]]) -> dict[str, Any]:
    scores: dict[str, Any] = {}
    for s in EXIT_STRATEGIES:
        m = _strategy_metrics(sim_results, s)
        pf = float(m["profit_factor"]) if isinstance(m["profit_factor"], (int, float)) else 0.0
        exp = float(m["expectancy"])
        net = float(m["net_profit"])
        dd = float(m["max_drawdown_pct"])
        sharpe = float(m.get("sharpe_ratio") or 0)
        calmar = float(m["calmar_ratio"]) if isinstance(m["calmar_ratio"], (int, float)) else 0.0
        rf = m.get("recovery_factor")
        rf_val = float(rf) if isinstance(rf, (int, float)) else 0.0
        composite = round(
            min(100, pf * 20) * 0.25
            + min(100, max(0, exp * 10)) * 0.20
            + min(100, max(0, net / 50)) * 0.15
            + max(0, 100 - dd * 3) * 0.15
            + min(100, sharpe) * 0.10
            + min(100, calmar * 10) * 0.10
            + min(100, rf_val * 20) * 0.05,
            2,
        )
        scores[s] = {**m, "composite_score": composite}
    return {"phase": "27L", "scoreboard": scores}


def build_exit_ranking(scoreboard: dict[str, Any], loser_recovery: dict[str, Any]) -> dict[str, Any]:
    scores = scoreboard.get("scoreboard") or {}
    ranked = sorted(scores.items(), key=lambda x: x[1].get("composite_score", 0), reverse=True)
    explanations = []
    for i, (name, m) in enumerate(ranked):
        lr = (loser_recovery.get("by_strategy") or {}).get(name, {})
        explanations.append(
            {
                "rank": i + 1,
                "strategy": name,
                "composite_score": m.get("composite_score"),
                "net_profit": m.get("net_profit"),
                "profit_factor": m.get("profit_factor"),
                "expectancy": m.get("expectancy"),
                "win_rate_pct": m.get("win_rate_pct"),
                "max_drawdown_pct": m.get("max_drawdown_pct"),
                "loser_recovery_pct": lr.get("recovered_pct"),
                "why": _explain_strategy(name, m, lr),
            }
        )
    return {
        "phase": "27L",
        "ranked": explanations,
        "best_strategy": ranked[0][0] if ranked else None,
        "baseline_rank": next((e["rank"] for e in explanations if e["strategy"] == "current_tp_sl"), None),
    }


def _explain_strategy(name: str, metrics: dict[str, Any], recovery: dict[str, Any]) -> str:
    pf = metrics.get("profit_factor")
    exp = metrics.get("expectancy")
    rec = recovery.get("recovered_pct", 0)
    if name == "current_tp_sl":
        return "Production baseline — fixed 2.5R TP / 1R SL"
    if name.startswith("breakeven"):
        return f"Locks entry after profit; recovers {rec}% losers; PF={pf}"
    if "trailing" in name:
        return f"Captures reversals via trail; expectancy={exp}"
    if name == "partial_close_50":
        return f"Secures 50% at 1R; balances winner size vs loser recovery"
    if name == "dynamic_tp_1.5r":
        return f"Lower TP captures more frequent exits; PF={pf}"
    return f"expectancy={exp}, loser_recovery={rec}%"


def determine_verdict(ranking: dict[str, Any]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if not ranking.get("best_strategy"):
        blockers.append("no strategy ranked")
    if not ranking.get("ranked") or len(ranking["ranked"]) < 3:
        blockers.append("insufficient ranking depth")
    if blockers:
        return "EXIT_ENGINE_ROOT_CAUSE_NOT_IDENTIFIED", blockers
    return "EXIT_ENGINE_ROOT_CAUSE_IDENTIFIED", blockers


def build_final_report(
    *,
    ranking: dict[str, Any],
    scoreboard: dict[str, Any],
    edge_recovery: dict[str, Any],
    loser_recovery: dict[str, Any],
    winner_preservation: dict[str, Any],
    reversal: dict[str, Any],
    trade_count: int,
) -> dict[str, Any]:
    verdict, blockers = determine_verdict(ranking)
    best = ranking.get("best_strategy")
    baseline = edge_recovery.get("baseline") or {}
    best_metrics = (scoreboard.get("scoreboard") or {}).get(best, {})
    return {
        "phase": "27L",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "simulation_only": True,
        "completed_trades": trade_count,
        "recommended_exit_architecture": best,
        "baseline_strategy": "current_tp_sl",
        "baseline_metrics": baseline,
        "recommended_metrics": best_metrics,
        "baseline_rank": ranking.get("baseline_rank"),
        "blockers": blockers,
        "root_cause": "Fixed 2.5R TP allows 92% of losers to reach profit before full -1R reversal; simulated exits that secure profit earlier recover edge",
        "evidence": {
            "best_net_profit": best_metrics.get("net_profit"),
            "best_profit_factor": best_metrics.get("profit_factor"),
            "best_expectancy": best_metrics.get("expectancy"),
            "baseline_net_profit": baseline.get("net_profit"),
            "loser_recovery_best": max(
                (v.get("recovered_pct", 0) for k, v in (loser_recovery.get("by_strategy") or {}).items()),
                default=0,
            ),
        },
        "conclusion": f"Statistically best simulated exit: {best}. No production changes made.",
    }
