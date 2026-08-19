"""Phase 27N — hybrid exit metrics, stability, Monte Carlo, ranking."""

from __future__ import annotations

import random
import statistics
from typing import Any

from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _profit_factor, _streaks
from tradingbot.ml.research.phase27a.metrics import _safe_pct
from tradingbot.ml.research.phase27h.stress_engine import apply_execution_delay, subsample_trades
from tradingbot.ml.research.phase27n.hybrid_simulators import ALL_STRATEGIES, BASELINE_STRATEGIES, HYBRID_STRATEGIES

INITIAL_BALANCE = 10_000.0
MC_SEED = 42
WINDOWS = (30, 60, 90, 180, 365)

HYBRID_LABELS = {
    "hybrid_a": "Partial 50% @1R + Structure Exit",
    "hybrid_b": "Partial 50% @1R + Time Exit 72b",
    "hybrid_c": "Breakeven @1R + Structure Exit",
    "hybrid_d": "Partial 50% + Stop +0.25R + Structure",
    "hybrid_e": "Partial 50% + ATR Trail after 1.5R",
}


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _std(vals: list[float]) -> float:
    return round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0


def _cv(vals: list[float]) -> float | None:
    m = _mean(vals)
    if not vals or m == 0:
        return None
    return round(_std(vals) / abs(m), 4)


def _pseudo_trades(
    sim_results: list[dict[str, Any]],
    strategy: str,
    *,
    trades: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    pseudo: list[dict[str, Any]] = []
    for i, row in enumerate(sim_results):
        s = row["strategies"][strategy]
        ts = row.get("timestamp") or i
        pseudo.append(
            {
                "pnl": float(s["pnl"]),
                "pnl_r": float(s.get("pnl_r") or 0.0),
                "direction": row.get("direction"),
                "duration_bars": s.get("duration_bars"),
                "timestamp": ts,
                "exit_timestamp": s.get("exit_timestamp") or ts,
            }
        )
    return pseudo


def strategy_metrics(
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    strategy: str,
) -> dict[str, Any]:
    pseudo = _pseudo_trades(sim_results, strategy)
    if not pseudo:
        return {"completed_trades": 0}

    pnls = [float(t["pnl"]) for t in pseudo]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
    dd_pct, dd_abs = _max_drawdown(eq)
    ret_pct = net / INITIAL_BALANCE * 100
    rs = [float(t["pnl_r"]) for t in pseudo]
    durs = [float(t["duration_bars"]) for t in pseudo if t.get("duration_bars") is not None]
    buys = sum(1 for t in pseudo if t.get("direction") == "BUY")
    sells = sum(1 for t in pseudo if t.get("direction") == "SELL")

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
        "average_r": _mean(rs),
        "sharpe_ratio": round(_sharpe(eq, "M5"), 4),
        "sortino_ratio": round(_sortino(eq, "M5"), 4),
        "calmar_ratio": round(ret_pct / dd_pct, 4) if dd_pct > 0 else ("inf" if ret_pct > 0 else 0.0),
        "recovery_factor": _recovery_factor(net, dd_abs),
        "max_drawdown_pct": round(dd_pct, 4),
        "average_trade_duration_bars": _mean(durs),
        "average_mae_r": base_mae,
        "average_mfe_r": base_mfe,
    }


def build_window_strategy_map(
    *,
    days: int,
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    meta: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    out = {s: strategy_metrics(trades, sim_results, s) for s in ALL_STRATEGIES}
    return {
        "phase": "27N",
        "window_days": days,
        "completed_trades_baseline": len(trades),
        "bars_evaluated": meta.get("bars_evaluated"),
        "strategies": out,
    }


def build_hybrid_report(hybrid: str, window_data: dict[int, dict[str, Any]]) -> dict[str, Any]:
    windows: dict[str, Any] = {}
    pf_vals: list[float] = []
    exp_vals: list[float] = []
    net_vals: list[float] = []
    for days in sorted(window_data.keys()):
        m = (window_data[days].get("strategies") or {}).get(hybrid, {})
        windows[str(days)] = m
        pfv = m.get("profit_factor")
        if isinstance(pfv, (int, float)):
            pf_vals.append(float(pfv))
        exp_vals.append(float(m.get("expectancy") or 0))
        net_vals.append(float(m.get("net_profit") or 0))
    best = max(net_vals) if net_vals else 0
    worst = min(net_vals) if net_vals else 0
    best_w = str(WINDOWS[net_vals.index(best)]) if net_vals else None
    worst_w = str(WINDOWS[net_vals.index(worst)]) if net_vals else None
    return {
        "phase": "27N",
        "hybrid": hybrid,
        "label": HYBRID_LABELS.get(hybrid, hybrid),
        "windows": windows,
        "summary": {
            "mean_profit_factor": _mean(pf_vals),
            "mean_expectancy": _mean(exp_vals),
            "mean_net_profit": _mean(net_vals),
            "variance_expectancy": round(_std(exp_vals) ** 2, 6),
            "cv_expectancy": _cv(exp_vals),
            "best_window": best_w,
            "best_net_profit": round(best, 4),
            "worst_window": worst_w,
            "worst_net_profit": round(worst, 4),
        },
    }


def build_stability_report(window_data: dict[int, dict[str, Any]]) -> dict[str, Any]:
    by_strategy: dict[str, Any] = {}
    for strategy in ALL_STRATEGIES:
        pf: list[float] = []
        exp: list[float] = []
        wr: list[float] = []
        net: list[float] = []
        ranks: list[int] = []
        for days in sorted(window_data.keys()):
            rep = window_data[days]
            m = (rep.get("strategies") or {}).get(strategy, {})
            if not m.get("completed_trades"):
                continue
            pfv = m.get("profit_factor")
            if isinstance(pfv, (int, float)):
                pf.append(float(pfv))
            exp.append(float(m.get("expectancy") or 0))
            wr.append(float(m.get("win_rate_pct") or 0))
            net.append(float(m.get("net_profit") or 0))
        for days in sorted(window_data.keys()):
            ordered = sorted(
                ALL_STRATEGIES,
                key=lambda s: float(
                    (window_data[days].get("strategies") or {}).get(s, {}).get("expectancy") or -1e9
                ),
                reverse=True,
            )
            if strategy in ordered:
                ranks.append(ordered.index(strategy) + 1)
        best_net = max(net) if net else 0
        worst_net = min(net) if net else 0
        consistency = round(100 - min(50, (_std(exp) or 0) * 10) - min(30, (_std(pf) or 0) * 20), 2)
        by_strategy[strategy] = {
            "windows_measured": len(net),
            "variance_profit_factor": round(_std(pf) ** 2, 6) if pf else 0,
            "variance_expectancy": round(_std(exp) ** 2, 6) if exp else 0,
            "variance_win_rate": round(_std(wr) ** 2, 6) if wr else 0,
            "variance_net_profit": round(_std(net) ** 2, 2) if net else 0,
            "cv_profit_factor": _cv(pf),
            "cv_expectancy": _cv(exp),
            "cv_net_profit": _cv(net),
            "consistency_score": max(0.0, consistency),
            "mean_rank": _mean([float(r) for r in ranks]),
            "best_window_net": round(best_net, 4),
            "worst_window_net": round(worst_net, 4),
            "mean_profit_factor": _mean(pf),
            "mean_expectancy": _mean(exp),
            "mean_net_profit": _mean(net),
        }
    return {"phase": "27N", "by_strategy": by_strategy}


def _equity_smoothness(eq: list[dict[str, Any]]) -> float:
    if len(eq) < 3:
        return 0.0
    rets = []
    for i in range(1, len(eq)):
        prev = float(eq[i - 1]["equity"])
        cur = float(eq[i]["equity"])
        if prev > 0:
            rets.append((cur - prev) / prev)
    if len(rets) < 2:
        return 0.0
    vol = statistics.stdev(rets)
    return round(1.0 / (1.0 + vol * 100), 4) if vol > 0 else 1.0


def build_equity_comparison(
    sim_results_30: list[dict[str, Any]],
    *,
    compare: tuple[str, ...] = (
        "current_tp_sl",
        "time_exit",
        "partial_close_50",
        "structure_exit",
        "hybrid_a",
        "hybrid_b",
        "hybrid_c",
        "hybrid_d",
        "hybrid_e",
    ),
) -> dict[str, Any]:
    curves: dict[str, Any] = {}
    smoothness: dict[str, float] = {}
    for strategy in compare:
        pseudo = _pseudo_trades(sim_results_30, strategy)
        eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
        curves[strategy] = eq
        smoothness[strategy] = _equity_smoothness(eq)
    smoothest = max(smoothness, key=smoothness.get) if smoothness else None
    return {
        "phase": "27N",
        "window_days": 30,
        "equity_curves": curves,
        "smoothness_score": smoothness,
        "smoothest_equity_curve": smoothest,
    }


def _recovery_speed(eq: list[dict[str, Any]]) -> float | None:
    if len(eq) < 2:
        return None
    peak = float(eq[0]["equity"])
    trough_idx = 0
    max_dd = 0.0
    for i, pt in enumerate(eq):
        v = float(pt["equity"])
        peak = max(peak, v)
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
            trough_idx = i
    if max_dd <= 0:
        return 0.0
    for j in range(trough_idx + 1, len(eq)):
        if float(eq[j]["equity"]) >= peak:
            return round(j - trough_idx, 2)
    return None


def _consecutive_stats(trades: list[dict[str, Any]]) -> dict[str, float]:
    ordered = sorted(trades, key=lambda t: t.get("exit_timestamp") or t.get("timestamp"))
    win_runs: list[int] = []
    loss_runs: list[int] = []
    cur_w = cur_l = 0
    largest_win = largest_loss = 0.0
    for t in ordered:
        pnl = float(t.get("pnl", 0))
        largest_win = max(largest_win, pnl)
        largest_loss = min(largest_loss, pnl)
        if pnl > 0:
            cur_w += 1
            if cur_l:
                loss_runs.append(cur_l)
            cur_l = 0
        elif pnl < 0:
            cur_l += 1
            if cur_w:
                win_runs.append(cur_w)
            cur_w = 0
        else:
            if cur_w:
                win_runs.append(cur_w)
            if cur_l:
                loss_runs.append(cur_l)
            cur_w = cur_l = 0
    if cur_w:
        win_runs.append(cur_w)
    if cur_l:
        loss_runs.append(cur_l)
    streaks = _streaks(ordered)
    return {
        **streaks,
        "largest_winner": round(largest_win, 4),
        "largest_loser": round(largest_loss, 4),
        "average_consecutive_wins": _mean([float(x) for x in win_runs]),
        "average_consecutive_losses": _mean([float(x) for x in loss_runs]),
    }


def build_risk_comparison(sim_results_30: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for strategy in ALL_STRATEGIES:
        pseudo = _pseudo_trades(sim_results_30, strategy)
        eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
        stats = _consecutive_stats(pseudo)
        stats["recovery_bars_after_max_dd"] = _recovery_speed(eq)
        out[strategy] = stats
    return {"phase": "27N", "window_days": 30, "by_strategy": out}


def _mc_metrics(trades: list[dict[str, Any]], *, simulations: int = 1000) -> dict[str, Any]:
    rng = random.Random(MC_SEED)
    nets: list[float] = []
    for _ in range(simulations):
        shuffled = trades.copy()
        rng.shuffle(shuffled)
        nets.append(sum(float(t["pnl"]) for t in shuffled))
    nets.sort()
    return {
        "simulations": simulations,
        "median_net_profit": round(statistics.median(nets), 4),
        "p05_net_profit": round(nets[int(len(nets) * 0.05)], 4),
        "pct_profitable_sequences": _safe_pct(sum(1 for n in nets if n > 0), len(nets)),
    }


def build_montecarlo_report(
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    frame: Any,
) -> dict[str, Any]:
    rng = random.Random(MC_SEED)
    out: dict[str, Any] = {"phase": "27N", "strategies": {}}
    for strategy in ALL_STRATEGIES:
        strat_trades = [{"pnl": float(r["strategies"][strategy]["pnl"])} for r in sim_results]
        seq = _mc_metrics(strat_trades, simulations=1000)
        missed: dict[str, Any] = {}
        for pct in (0.10, 0.20, 0.30):
            keep = 1.0 - pct
            nets = []
            if strat_trades:
                for _ in range(100):
                    sub = subsample_trades([{"pnl": t["pnl"]} for t in strat_trades], keep, rng)
                    nets.append(sum(float(t["pnl"]) for t in sub))
            missed[f"{int(pct * 100)}pct"] = {
                "median_net": round(statistics.median(nets), 4) if nets else 0.0,
                "worst_net": round(min(nets), 4) if nets else 0.0,
            }
        delay_net = None
        failure_net = None
        if strategy == "current_tp_sl" and trades and frame is not None and not getattr(frame, "empty", True):
            d1 = apply_execution_delay(trades, 1, frame, symbol="XAUUSD")
            delay_net = round(sum(float(t["pnl"]) for t in d1), 4)
            fail_nets = []
            for _ in range(100):
                sub = subsample_trades(trades, 0.90, rng)
                fail_nets.append(sum(float(t["pnl"]) for t in sub))
            failure_net = round(statistics.mean(fail_nets), 4)
        out["strategies"][strategy] = {
            "sequence_shuffle": seq,
            "missed_trades": missed,
            "delay_1_bar_baseline_pnl": delay_net,
            "failure_10pct_mean_pnl": failure_net,
        }
    return out


def build_comparison_matrix(window_data: dict[int, dict[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, dict[str, Any]] = {}
    for strategy in ALL_STRATEGIES:
        row: dict[str, Any] = {"strategy": strategy}
        for days in sorted(window_data.keys()):
            m = (window_data[days].get("strategies") or {}).get(strategy, {})
            row[f"{days}d_pf"] = m.get("profit_factor")
            row[f"{days}d_expectancy"] = m.get("expectancy")
            row[f"{days}d_net"] = m.get("net_profit")
            row[f"{days}d_dd"] = m.get("max_drawdown_pct")
        matrix[strategy] = row
    return {"phase": "27N", "matrix": matrix}


def build_global_ranking(
    stability: dict[str, Any],
    montecarlo: dict[str, Any],
    equity: dict[str, Any],
) -> dict[str, Any]:
    ranked = []
    for strategy in ALL_STRATEGIES:
        stab = (stability.get("by_strategy") or {}).get(strategy, {})
        mc = (montecarlo.get("strategies") or {}).get(strategy, {})
        seq = mc.get("sequence_shuffle") or {}
        smooth = (equity.get("smoothness_score") or {}).get(strategy, 0)
        composite = round(
            float(stab.get("mean_profit_factor") or 0) * 15
            + float(stab.get("mean_expectancy") or 0) * 5
            + float(stab.get("consistency_score") or 0) * 0.4
            + float(seq.get("pct_profitable_sequences") or 0) * 0.2
            + float(smooth) * 10
            - float(stab.get("mean_rank") or 5) * 2,
            2,
        )
        ranked.append(
            {
                "strategy": strategy,
                "is_hybrid": strategy in HYBRID_STRATEGIES,
                "mean_profit_factor": stab.get("mean_profit_factor"),
                "mean_expectancy": stab.get("mean_expectancy"),
                "mean_net_profit": stab.get("mean_net_profit"),
                "consistency_score": stab.get("consistency_score"),
                "mean_rank": stab.get("mean_rank"),
                "mc_pct_profitable": seq.get("pct_profitable_sequences"),
                "equity_smoothness": smooth,
                "composite_score": composite,
            }
        )
    ranked.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, row in enumerate(ranked):
        row["global_rank"] = i + 1
    return {
        "phase": "27N",
        "ranked": ranked,
        "global_winner": ranked[0]["strategy"] if ranked else None,
        "best_hybrid": next((r["strategy"] for r in ranked if r["is_hybrid"]), None),
        "best_baseline": next((r["strategy"] for r in ranked if not r["is_hybrid"]), None),
    }


def determine_verdict(global_ranking: dict[str, Any]) -> tuple[str, list[str]]:
    ranked = global_ranking.get("ranked") or []
    if not ranked:
        return "HYBRID_EXIT_INCONCLUSIVE", ["no ranking data"]
    best = ranked[0]
    best_hybrid = global_ranking.get("best_hybrid")
    blockers: list[str] = []
    if not best_hybrid:
        return "HYBRID_EXIT_NOT_BETTER", ["no hybrid strategies evaluated"]

    hybrid_rows = [r for r in ranked if r.get("is_hybrid")]
    baseline_rows = [r for r in ranked if not r.get("is_hybrid")]
    best_h = max(hybrid_rows, key=lambda x: x["composite_score"]) if hybrid_rows else None
    best_b = max(baseline_rows, key=lambda x: x["composite_score"]) if baseline_rows else None

    if best.get("is_hybrid"):
        beats_all = all(
            best["composite_score"] > r["composite_score"]
            for r in baseline_rows
        )
        if beats_all:
            return "HYBRID_EXIT_OUTPERFORMS_ALL", blockers
        blockers.append("hybrid ranks #1 but does not beat all baselines on composite")
        return "HYBRID_EXIT_INCONCLUSIVE", blockers

    if best_h and best_b and best_h["composite_score"] > best_b["composite_score"]:
        blockers.append("best hybrid beats best baseline but not global #1")
        return "HYBRID_EXIT_INCONCLUSIVE", blockers

    return "HYBRID_EXIT_NOT_BETTER", blockers


def build_final_report(
    *,
    verdict: str,
    blockers: list[str],
    global_ranking: dict[str, Any],
    window_data: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "phase": "27N",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "simulation_only": True,
        "windows_tested": sorted(window_data.keys()),
        "global_winner": global_ranking.get("global_winner"),
        "best_hybrid": global_ranking.get("best_hybrid"),
        "best_baseline": global_ranking.get("best_baseline"),
        "blockers": blockers,
        "conclusion": (
            f"Global winner: {global_ranking.get('global_winner')}. "
            f"Best hybrid: {global_ranking.get('best_hybrid')}. Verdict: {verdict}."
        ),
    }
