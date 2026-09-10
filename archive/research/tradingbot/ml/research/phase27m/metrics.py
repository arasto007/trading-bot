"""Phase 27M — cross-window exit robustness metrics."""

from __future__ import annotations

import random
import statistics
from collections import Counter
from typing import Any

from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _profit_factor
from tradingbot.ml.research.phase27a.metrics import _safe_pct
from tradingbot.ml.research.phase27h.stress_engine import apply_execution_delay, compute_atr
from tradingbot.ml.research.phase27h.stress_engine import subsample_trades as mc_subsample
from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame
from tradingbot.ml.research.phase27m.window_runner import STRATEGIES

INITIAL_BALANCE = 10_000.0
MC_SEED = 42
WINDOWS = (30, 60, 90, 180, 365)


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _std(vals: list[float]) -> float:
    return round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0


def _cv(vals: list[float]) -> float | None:
    if not vals or _mean(vals) == 0:
        return None
    return round(_std(vals) / abs(_mean(vals)), 4)


def strategy_window_metrics(
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    strategy: str,
) -> dict[str, Any]:
    pseudo = []
    for i, row in enumerate(sim_results):
        s = row["strategies"][strategy]
        pseudo.append(
            {
                "pnl": s["pnl"],
                "pnl_r": s.get("pnl_r", 0.0),
                "direction": row.get("direction"),
                "duration_bars": s.get("duration_bars"),
                "timestamp": row.get("timestamp") or i,
            }
        )
    if not pseudo:
        return {"trade_count": 0}

    pnls = [float(t["pnl"]) for t in pseudo]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
    dd_pct, dd_abs = _max_drawdown(eq)
    ret_pct = net / INITIAL_BALANCE * 100
    rs = [float(t["pnl_r"]) for t in pseudo]
    buys = sum(1 for t in pseudo if t.get("direction") == "BUY")
    sells = sum(1 for t in pseudo if t.get("direction") == "SELL")
    durs = [float(t["duration_bars"]) for t in pseudo if t.get("duration_bars") is not None]

    base_mae = _mean([float(tr.get("mae") or 0) for tr in trades]) if strategy == "current_tp_sl" else None
    base_mfe = _mean([float(tr.get("mfe") or 0) for tr in trades]) if strategy == "current_tp_sl" else None

    return {
        "strategy": strategy,
        "completed_trades": len(pseudo),
        "buy_count": buys,
        "sell_count": sells,
        "win_rate_pct": _safe_pct(len(wins), len(pseudo)),
        "profit_factor": _profit_factor(pseudo),
        "expectancy": round(net / len(pseudo), 4),
        "net_profit": round(net, 4),
        "average_winner": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "average_loser": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "sharpe_ratio": round(_sharpe(eq, "M5"), 4),
        "sortino_ratio": round(_sortino(eq, "M5"), 4),
        "calmar_ratio": round(ret_pct / dd_pct, 4) if dd_pct > 0 else ("inf" if ret_pct > 0 else 0.0),
        "recovery_factor": _recovery_factor(net, dd_abs),
        "max_drawdown_pct": round(dd_pct, 4),
        "average_trade_duration_bars": _mean(durs),
        "average_r": _mean(rs),
        "average_mae_r": base_mae,
        "average_mfe_r": base_mfe,
    }


def build_window_report(
    *,
    days: int,
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    meta: dict[str, Any],
    window: Any,
) -> dict[str, Any]:
    strategies = {s: strategy_window_metrics(trades, sim_results, s) for s in STRATEGIES}
    ranked = sorted(
        strategies.items(),
        key=lambda x: float(x[1].get("expectancy") or 0),
        reverse=True,
    )
    return {
        "phase": "27M",
        "window_days": days,
        "window_bars": len(window) if hasattr(window, "__len__") else 0,
        "bars_evaluated": meta.get("bars_evaluated"),
        "completed_trades_baseline": len(trades),
        "strategies": strategies,
        "window_winner": ranked[0][0] if ranked else None,
        "replay_meta": {k: meta[k] for k in meta if k != "portfolio_timeline"},
    }


def build_stability_analysis(window_reports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"phase": "27M", "by_strategy": {}}
    for strategy in STRATEGIES:
        pf: list[float] = []
        exp: list[float] = []
        wr: list[float] = []
        dd: list[float] = []
        net: list[float] = []
        for days, rep in window_reports.items():
            m = (rep.get("strategies") or {}).get(strategy, {})
            if not m or not m.get("completed_trades"):
                continue
            pfv = m.get("profit_factor")
            if isinstance(pfv, (int, float)):
                pf.append(float(pfv))
            exp.append(float(m.get("expectancy") or 0))
            wr.append(float(m.get("win_rate_pct") or 0))
            dd.append(float(m.get("max_drawdown_pct") or 0))
            net.append(float(m.get("net_profit") or 0))
        pf_var = round(_std(pf) ** 2, 6) if pf else 0
        exp_var = round(_std(exp) ** 2, 6) if exp else 0
        stability = round(
            100
            - min(50, pf_var * 100)
            - min(30, exp_var * 5)
            - min(20, (_std(dd) or 0) * 2),
            2,
        )
        out["by_strategy"][strategy] = {
            "windows_measured": len(net),
            "variance_profit_factor": pf_var,
            "variance_expectancy": exp_var,
            "variance_win_rate": round(_std(wr) ** 2, 6) if wr else 0,
            "variance_drawdown": round(_std(dd) ** 2, 6) if dd else 0,
            "variance_net_profit": round(_std(net) ** 2, 2) if net else 0,
            "cv_profit_factor": _cv(pf),
            "cv_expectancy": _cv(exp),
            "cv_net_profit": _cv(net),
            "stability_score": max(0.0, stability),
            "mean_profit_factor": _mean(pf),
            "mean_expectancy": _mean(exp),
            "mean_net_profit": _mean(net),
        }
    return out


def _mc_metrics(trades: list[dict[str, Any]], *, simulations: int = 1000) -> dict[str, Any]:
    rng = random.Random(MC_SEED)
    nets: list[float] = []
    pfs: list[float] = []
    for _ in range(simulations):
        shuffled = trades.copy()
        rng.shuffle(shuffled)
        net = sum(float(t["pnl"]) for t in shuffled)
        nets.append(net)
        pfs.append(float(_profit_factor([{"pnl": t["pnl"]} for t in shuffled])))
    nets.sort()
    return {
        "simulations": simulations,
        "median_net_profit": round(statistics.median(nets), 4),
        "p05_net_profit": round(nets[int(len(nets) * 0.05)], 4),
        "median_profit_factor": round(statistics.median(pfs), 4),
        "pct_profitable_sequences": _safe_pct(sum(1 for n in nets if n > 0), len(nets)),
    }


def build_montecarlo_analysis(
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    frame: Any,
) -> dict[str, Any]:
    rng = random.Random(MC_SEED)
    atr = compute_atr(frame) if frame is not None and not getattr(frame, "empty", True) else None
    out: dict[str, Any] = {"phase": "27M", "strategies": {}}

    for strategy in STRATEGIES:
        strat_trades = [{"pnl": float(r["strategies"][strategy]["pnl"])} for r in sim_results]
        seq = _mc_metrics(strat_trades, simulations=1000)
        missed: dict[str, Any] = {}
        for pct in (0.10, 0.20, 0.30):
            keep = 1.0 - pct
            nets = []
            for _ in range(100):
                sub = mc_subsample(
                    [{"pnl": t["pnl"]} for t in strat_trades],
                    keep,
                    rng,
                )
                nets.append(sum(float(t["pnl"]) for t in sub))
            missed[f"{int(pct*100)}pct"] = {
                "median_net": round(statistics.median(nets), 4),
                "worst_net": round(min(nets), 4),
            }
        delay_net = None
        failure_net = None
        if strategy == "current_tp_sl" and trades and atr is not None:
            d1 = apply_execution_delay(trades, 1, frame, symbol="XAUUSD")
            delay_net = round(sum(float(t["pnl"]) for t in d1), 4)
            fail_nets = []
            for _ in range(100):
                sub = mc_subsample(trades, 0.90, rng)
                fail_nets.append(sum(float(t["pnl"]) for t in sub))
            failure_net = round(statistics.mean(fail_nets), 4)
        out["strategies"][strategy] = {
            "sequence_shuffle": seq,
            "missed_trades": missed,
            "delay_1_bar_baseline_pnl": delay_net,
            "failure_10pct_mean_pnl": failure_net,
        }
    return out


def build_walkforward_analysis(window_reports: dict[int, dict[str, Any]]) -> dict[str, Any]:
    winners: list[str] = []
    ranks: dict[str, list[int]] = {s: [] for s in STRATEGIES}
    for days in sorted(window_reports.keys()):
        rep = window_reports[days]
        winner = rep.get("window_winner")
        if winner:
            winners.append(winner)
        ordered = sorted(
            STRATEGIES,
            key=lambda s: float((rep.get("strategies") or {}).get(s, {}).get("expectancy") or -1e9),
            reverse=True,
        )
        for i, s in enumerate(ordered):
            ranks[s].append(i + 1)
    wc = Counter(winners)
    consistent = len(wc) == 1 and len(winners) >= 3
    return {
        "phase": "27M",
        "window_winners": {str(k): window_reports[k].get("window_winner") for k in sorted(window_reports)},
        "winner_frequency": dict(wc),
        "mean_rank_by_strategy": {s: _mean([float(r) for r in rs]) for s, rs in ranks.items() if rs},
        "same_winner_all_windows": consistent,
        "dominant_winner": wc.most_common(1)[0][0] if wc else None,
        "explanation": (
            "Same exit wins every window — robust across periods"
            if consistent
            else "Rankings shift by window — period sensitivity detected"
        ),
    }


def build_overfitting_report(
    window_reports: dict[int, dict[str, Any]],
    stability: dict[str, Any],
) -> dict[str, Any]:
    focus = ("time_exit", "dynamic_tp_1.5r", "structure_exit", "atr_exit")
    short = window_reports.get(30, {})
    long_w = window_reports.get(180) or window_reports.get(365) or {}
    findings: dict[str, Any] = {}
    for s in focus:
        m30 = (short.get("strategies") or {}).get(s, {})
        mlong = (long_w.get("strategies") or {}).get(s, {})
        stab = (stability.get("by_strategy") or {}).get(s, {})
        pf30 = float(m30.get("profit_factor") or 0) if isinstance(m30.get("profit_factor"), (int, float)) else 0
        pfl = float(mlong.get("profit_factor") or 0) if isinstance(mlong.get("profit_factor"), (int, float)) else 0
        only_june = pf30 > 1.2 and pfl < 1.0
        findings[s] = {
            "pf_30d": m30.get("profit_factor"),
            "pf_long_window": mlong.get("profit_factor"),
            "expectancy_30d": m30.get("expectancy"),
            "expectancy_long": mlong.get("expectancy"),
            "stability_score": stab.get("stability_score"),
            "cv_expectancy": stab.get("cv_expectancy"),
            "june_only_success": only_june,
            "robust": pf30 >= 1.0 and pfl >= 1.0 and not only_june,
        }
    june_only = [k for k, v in findings.items() if v.get("june_only_success")]
    robust = [k for k, v in findings.items() if v.get("robust")]
    return {
        "phase": "27M",
        "strategies_tested": list(focus),
        "findings": findings,
        "june_2026_only_strategies": june_only,
        "cross_window_robust_strategies": robust,
        "overfit_detected": len(june_only) > len(robust),
    }


def build_global_ranking(
    window_reports: dict[int, dict[str, Any]],
    stability: dict[str, Any],
    montecarlo: dict[str, Any],
    walkforward: dict[str, Any],
) -> dict[str, Any]:
    ranked_rows = []
    for strategy in STRATEGIES:
        stab = (stability.get("by_strategy") or {}).get(strategy, {})
        mc = (montecarlo.get("strategies") or {}).get(strategy, {})
        seq = mc.get("sequence_shuffle") or {}
        pf_vals = []
        exp_vals = []
        dd_vals = []
        for rep in window_reports.values():
            m = (rep.get("strategies") or {}).get(strategy, {})
            pfv = m.get("profit_factor")
            if isinstance(pfv, (int, float)):
                pf_vals.append(float(pfv))
            exp_vals.append(float(m.get("expectancy") or 0))
            dd_vals.append(float(m.get("max_drawdown_pct") or 0))
        composite = round(
            _mean(pf_vals) * 15
            + _mean(exp_vals) * 5
            + float(stab.get("stability_score") or 0) * 0.3
            + float(seq.get("pct_profitable_sequences") or 0) * 0.2
            - _mean(dd_vals) * 0.5
            + (10 if strategy == walkforward.get("dominant_winner") else 0),
            2,
        )
        ranked_rows.append(
            {
                "strategy": strategy,
                "mean_profit_factor": _mean(pf_vals),
                "mean_expectancy": _mean(exp_vals),
                "mean_max_drawdown_pct": _mean(dd_vals),
                "stability_score": stab.get("stability_score"),
                "mc_pct_profitable_sequences": seq.get("pct_profitable_sequences"),
                "walkforward_mean_rank": (walkforward.get("mean_rank_by_strategy") or {}).get(strategy),
                "composite_score": composite,
            }
        )
    ranked_rows.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, row in enumerate(ranked_rows):
        row["global_rank"] = i + 1
    return {"phase": "27M", "ranked": ranked_rows, "global_winner": ranked_rows[0]["strategy"] if ranked_rows else None}


def determine_verdict(
    *,
    overfitting: dict[str, Any],
    walkforward: dict[str, Any],
    global_ranking: dict[str, Any],
    stability: dict[str, Any],
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    winner = global_ranking.get("global_winner")
    if not winner:
        blockers.append("no global winner")
    if overfitting.get("overfit_detected"):
        blockers.append("june-only overfitting detected for key strategies")
    wf = walkforward.get("winner_frequency") or {}
    if len(wf) > 3:
        blockers.append("too many different window winners")
    stab_w = (stability.get("by_strategy") or {}).get(winner or "", {})
    if float(stab_w.get("stability_score") or 0) < 40:
        blockers.append(f"low stability score for {winner}")

    robust_count = len(overfitting.get("cross_window_robust_strategies") or [])
    if overfitting.get("overfit_detected") and robust_count == 0:
        return "EXIT_STRATEGY_OVERFIT", blockers
    if winner and robust_count >= 1 and float(stab_w.get("stability_score") or 0) >= 40:
        return "EXIT_STRATEGY_ROBUST", blockers
    if blockers:
        return "EXIT_STRATEGY_INCONCLUSIVE", blockers
    return "EXIT_STRATEGY_ROBUST", blockers


def build_final_report(
    *,
    verdict: str,
    blockers: list[str],
    global_ranking: dict[str, Any],
    walkforward: dict[str, Any],
    overfitting: dict[str, Any],
    window_reports: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "phase": "27M",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "simulation_only": True,
        "windows_tested": sorted(window_reports.keys()),
        "global_winner": global_ranking.get("global_winner"),
        "walkforward": {
            "dominant_winner": walkforward.get("dominant_winner"),
            "winner_frequency": walkforward.get("winner_frequency"),
            "same_winner_all_windows": walkforward.get("same_winner_all_windows"),
        },
        "overfitting_summary": {
            "june_only": overfitting.get("june_2026_only_strategies"),
            "robust": overfitting.get("cross_window_robust_strategies"),
        },
        "blockers": blockers,
        "conclusion": f"Global exit ranking winner: {global_ranking.get('global_winner')}. Verdict: {verdict}.",
    }
