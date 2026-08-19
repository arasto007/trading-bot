"""Phase 28A — A/B metrics, head-to-head, Monte Carlo, decision matrix."""

from __future__ import annotations

import random
import statistics
from typing import Any

from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _profit_factor, _streaks
from tradingbot.ml.research.phase27a.metrics import _safe_pct
from tradingbot.ml.research.phase27h.stress_engine import apply_execution_delay, subsample_trades
from tradingbot.ml.research.phase28a.window_runner import STRATEGY_A, STRATEGY_B

INITIAL_BALANCE = 10_000.0
MC_SEED = 42
TIE_THRESHOLD_USD = 0.50


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _median(vals: list[float]) -> float:
    return round(statistics.median(vals), 4) if vals else 0.0


def _pf_val(pf: Any) -> float:
    if isinstance(pf, (int, float)):
        return float(pf)
    return 0.0


def _pseudo(sim_results: list[dict[str, Any]], strategy: str) -> list[dict[str, Any]]:
    pseudo: list[dict[str, Any]] = []
    for i, row in enumerate(sim_results):
        s = row[strategy]
        ts = row.get("timestamp") or i
        pseudo.append(
            {
                "entry_id": row.get("entry_id"),
                "pnl": float(s["pnl"]),
                "pnl_r": float(s.get("pnl_r") or 0.0),
                "direction": row.get("direction"),
                "duration_bars": s.get("duration_bars"),
                "exit_reason": s.get("exit_reason"),
                "timestamp": ts,
                "exit_timestamp": s.get("exit_timestamp") or ts,
            }
        )
    return pseudo


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


def strategy_full_metrics(
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    strategy: str,
    *,
    label: str,
) -> dict[str, Any]:
    pseudo = _pseudo(sim_results, strategy)
    if not pseudo:
        return {"strategy": strategy, "label": label, "completed_trades": 0}

    pnls = [float(t["pnl"]) for t in pseudo]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
    dd_pct, dd_abs = _max_drawdown(eq)
    ret_pct = net / INITIAL_BALANCE * 100
    rs = [float(t["pnl_r"]) for t in pseudo]
    durs = [float(t["duration_bars"]) for t in pseudo if t.get("duration_bars") is not None]
    streaks = _streaks(pseudo)
    ordered = sorted(pseudo, key=lambda t: t.get("exit_timestamp") or t.get("timestamp"))
    largest_win = max(pnls) if pnls else 0.0
    largest_loss = min(pnls) if pnls else 0.0

    base_mae = _mean([float(tr.get("mae") or 0) for tr in trades])
    base_mfe = _mean([float(tr.get("mfe") or 0) for tr in trades])

    return {
        "strategy": strategy,
        "label": label,
        "completed_trades": len(pseudo),
        "buy_count": sum(1 for t in pseudo if t.get("direction") == "BUY"),
        "sell_count": sum(1 for t in pseudo if t.get("direction") == "SELL"),
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
        "largest_winner": round(largest_win, 4),
        "largest_loser": round(largest_loss, 4),
        "longest_losing_streak": streaks.get("longest_losing_streak", 0),
        "recovery_bars_after_max_dd": _recovery_speed(eq),
        "equity_curve_smoothness": _equity_smoothness(eq),
    }


def build_strategy_results(
    *,
    strategy: str,
    label: str,
    window_data: dict[int, dict[str, Any]],
    aggregate_trades: list[dict[str, Any]],
    aggregate_sim: list[dict[str, Any]],
) -> dict[str, Any]:
    aggregate = strategy_full_metrics(aggregate_trades, aggregate_sim, strategy, label=label)
    windows = {
        str(days): strategy_full_metrics(
            window_data[days]["trades"],
            window_data[days]["sim"],
            strategy,
            label=label,
        )
        for days in sorted(window_data.keys())
    }
    return {
        "phase": "28A",
        "strategy": strategy,
        "label": label,
        "aggregate": aggregate,
        "windows": windows,
    }


def build_paired_trade_comparison(sim_results: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    hybrid_wins = time_wins = draws = 0
    dollar_adv: list[float] = []
    r_adv: list[float] = []

    for row in sim_results:
        a = row[STRATEGY_A]
        b = row[STRATEGY_B]
        pnl_a = float(a["pnl"])
        pnl_b = float(b["pnl"])
        diff = round(pnl_a - pnl_b, 4)
        r_diff = round(float(a.get("pnl_r") or 0) - float(b.get("pnl_r") or 0), 4)
        dollar_adv.append(diff)
        r_adv.append(r_diff)

        if abs(diff) <= TIE_THRESHOLD_USD:
            winner = "draw"
            draws += 1
        elif diff > 0:
            winner = STRATEGY_A
            hybrid_wins += 1
        else:
            winner = STRATEGY_B
            time_wins += 1

        pairs.append(
            {
                "entry_id": row.get("entry_id"),
                "timestamp": row.get("timestamp"),
                "direction": row.get("direction"),
                "hybrid_b_pnl": pnl_a,
                "time_exit_pnl": pnl_b,
                "profit_difference": diff,
                "r_difference": r_diff,
                "winner": winner,
                "hybrid_exit_reason": a.get("exit_reason"),
                "time_exit_reason": b.get("exit_reason"),
                "hybrid_duration_bars": a.get("duration_bars"),
                "time_exit_duration_bars": b.get("duration_bars"),
            }
        )

    return {
        "phase": "28A",
        "paired_trade_count": len(pairs),
        "hybrid_wins": hybrid_wins,
        "time_exit_wins": time_wins,
        "draws": draws,
        "hybrid_win_pct": _safe_pct(hybrid_wins, len(pairs)),
        "time_exit_win_pct": _safe_pct(time_wins, len(pairs)),
        "average_dollar_advantage_hybrid": _mean(dollar_adv),
        "average_r_advantage_hybrid": _mean(r_adv),
        "median_dollar_advantage_hybrid": _median(dollar_adv),
        "median_r_advantage_hybrid": _median(r_adv),
        "pairs": pairs,
    }


def build_head_to_head(sim_results: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    recovered_losers = lost_winners = 0
    additional_profit = 0.0
    additional_dd_hybrid = 0.0

    for row in sim_results:
        a = row[STRATEGY_A]
        b = row[STRATEGY_B]
        pnl_a = float(a["pnl"])
        pnl_b = float(b["pnl"])
        diff = round(pnl_a - pnl_b, 4)
        additional_profit += diff

        if pnl_b < 0 and pnl_a > 0:
            recovered_losers += 1
        if pnl_b > 0 and pnl_a < 0:
            lost_winners += 1

        dur_a = int(a.get("duration_bars") or 0)
        dur_b = int(b.get("duration_bars") or 0)
        additional_dd_hybrid += min(0.0, pnl_a - pnl_b) if pnl_a < pnl_b else 0.0

        rows.append(
            {
                "entry_id": row.get("entry_id"),
                "same_entry": True,
                "profit_difference": diff,
                "exit_difference": {
                    "hybrid_reason": a.get("exit_reason"),
                    "time_reason": b.get("exit_reason"),
                },
                "duration_difference_bars": dur_a - dur_b,
                "recovered_loser": pnl_b < 0 and pnl_a > 0,
                "lost_winner": pnl_b > 0 and pnl_a < 0,
                "additional_profit_hybrid": diff,
            }
        )

    return {
        "phase": "28A",
        "trade_count": len(rows),
        "recovered_losers": recovered_losers,
        "lost_winners": lost_winners,
        "net_additional_profit_hybrid": round(additional_profit, 4),
        "additional_drawdown_hybrid": round(additional_dd_hybrid, 4),
        "trades": rows,
    }


def build_equity_comparison(sim_results: list[dict[str, Any]], *, window_days: int = 30) -> dict[str, Any]:
    curves: dict[str, Any] = {}
    smoothness: dict[str, float] = {}
    for strategy, label in ((STRATEGY_A, "Hybrid B"), (STRATEGY_B, "Time Exit")):
        pseudo = _pseudo(sim_results, strategy)
        eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
        curves[strategy] = {"label": label, "points": eq}
        smoothness[strategy] = _equity_smoothness(eq)
    return {
        "phase": "28A",
        "window_days": window_days,
        "equity_curves": curves,
        "smoothness_score": smoothness,
        "smoothest": max(smoothness, key=smoothness.get) if smoothness else None,
    }


def build_risk_comparison(sim_results: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for strategy, label in ((STRATEGY_A, "Hybrid B"), (STRATEGY_B, "Time Exit")):
        pseudo = _pseudo(sim_results, strategy)
        eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
        ordered = sorted(pseudo, key=lambda t: t.get("exit_timestamp") or t.get("timestamp"))
        streaks = _streaks(ordered)
        pnls = [float(t["pnl"]) for t in ordered]
        out[strategy] = {
            "label": label,
            "longest_losing_streak": streaks.get("longest_losing_streak", 0),
            "longest_winning_streak": streaks.get("longest_winning_streak", 0),
            "largest_winner": round(max(pnls), 4) if pnls else 0.0,
            "largest_loser": round(min(pnls), 4) if pnls else 0.0,
            "recovery_bars_after_max_dd": _recovery_speed(eq),
            "max_drawdown_pct": round(_max_drawdown(eq)[0], 4),
        }
    return {"phase": "28A", "by_strategy": out}


def _mc_block(trades: list[dict[str, Any]], *, simulations: int = 1000) -> dict[str, Any]:
    if not trades:
        return {"simulations": simulations, "median_net_profit": 0.0, "pct_profitable_sequences": 0.0}
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


def build_montecarlo_comparison(
    sim_results: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    frame: Any,
) -> dict[str, Any]:
    rng = random.Random(MC_SEED)
    out: dict[str, Any] = {"phase": "28A", "strategies": {}}
    for strategy, label in ((STRATEGY_A, "Hybrid B"), (STRATEGY_B, "Time Exit")):
        strat_trades = [{"pnl": float(r[strategy]["pnl"])} for r in sim_results]
        seq = _mc_block(strat_trades, simulations=1000)
        missed: dict[str, Any] = {}
        for pct in (0.10, 0.20, 0.30):
            keep = 1.0 - pct
            nets = []
            if strat_trades:
                for _ in range(100):
                    sub = subsample_trades(strat_trades, keep, rng)
                    nets.append(sum(float(t["pnl"]) for t in sub))
            missed[f"{int(pct * 100)}pct"] = {
                "median_net": round(statistics.median(nets), 4) if nets else 0.0,
                "worst_net": round(min(nets), 4) if nets else 0.0,
            }
        delay_net = failure_net = None
        if strategy == STRATEGY_B and trades and frame is not None and not getattr(frame, "empty", True):
            d1 = apply_execution_delay(trades, 1, frame, symbol="XAUUSD")
            delay_net = round(sum(float(t["pnl"]) for t in d1), 4)
            fail_nets = []
            for _ in range(100):
                sub = subsample_trades(trades, 0.90, rng)
                fail_nets.append(sum(float(t["pnl"]) for t in sub))
            failure_net = round(statistics.mean(fail_nets), 4)
        out["strategies"][strategy] = {
            "label": label,
            "sequence_shuffle": seq,
            "missed_trades": missed,
            "delay_1_bar_baseline_pnl": delay_net,
            "failure_10pct_mean_pnl": failure_net,
        }
    hb = out["strategies"][STRATEGY_A]["sequence_shuffle"]["median_net_profit"]
    te = out["strategies"][STRATEGY_B]["sequence_shuffle"]["median_net_profit"]
    out["robustness_winner"] = STRATEGY_A if hb > te else STRATEGY_B if te > hb else "tie"
    return out


def build_decision_matrix(
    strategy_a: dict[str, Any],
    strategy_b: dict[str, Any],
    paired: dict[str, Any],
    montecarlo: dict[str, Any],
    equity: dict[str, Any],
) -> dict[str, Any]:
    agg_a = strategy_a.get("aggregate") or {}
    agg_b = strategy_b.get("aggregate") or {}

    def _window_consistency(results: dict[str, Any]) -> float:
        nets = [float((results.get("windows") or {}).get(str(d), {}).get("net_profit") or 0) for d in (30, 60, 90, 180, 365)]
        nets = [n for n in nets if n != 0 or any((results.get("windows") or {}).get(str(d)) for d in (30, 60, 90, 180, 365))]
        if len(nets) < 2:
            return 50.0
        m = _mean(nets)
        if m == 0:
            return 50.0
        cv = (statistics.stdev(nets) / abs(m)) if len(nets) > 1 else 0
        return round(max(0, 100 - min(80, cv * 50)), 2)

    def _score(agg: dict[str, Any], results: dict[str, Any], strategy: str) -> dict[str, Any]:
        mc = (montecarlo.get("strategies") or {}).get(strategy, {}).get("sequence_shuffle") or {}
        smooth = (equity.get("smoothness_score") or {}).get(strategy, 0)
        pf = _pf_val(agg.get("profit_factor"))
        exp = float(agg.get("expectancy") or 0)
        dd = float(agg.get("max_drawdown_pct") or 0)
        sharpe = float(agg.get("sharpe_ratio") or 0)
        recovery = float(agg.get("recovery_factor") or 0) if isinstance(agg.get("recovery_factor"), (int, float)) else 0
        consistency = _window_consistency(results)
        risk_adj = sharpe
        composite = round(
            pf * 15
            + exp * 4
            + risk_adj * 2
            + float(mc.get("pct_profitable_sequences") or 0) * 0.15
            + float(smooth) * 12
            + consistency * 0.2
            - dd * 0.4
            + float(recovery) * 3,
            2,
        )
        return {
            "profit_factor": pf,
            "expectancy": exp,
            "max_drawdown_pct": dd,
            "recovery_factor": recovery,
            "stability_consistency": consistency,
            "monte_carlo_pct_profitable": mc.get("pct_profitable_sequences"),
            "equity_smoothness": smooth,
            "risk_adjusted_return": risk_adj,
            "composite_score": composite,
        }

    scores_a = _score(agg_a, strategy_a, STRATEGY_A)
    scores_b = _score(agg_b, strategy_b, STRATEGY_B)
    hybrid_paired_pct = float(paired.get("hybrid_win_pct") or 0)
    time_paired_pct = float(paired.get("time_exit_win_pct") or 0)

    criteria_wins = {"hybrid_b": 0, "time_exit": 0, "tie": 0}
    for key in ("profit_factor", "expectancy", "recovery_factor", "stability_consistency",
                "monte_carlo_pct_profitable", "equity_smoothness", "risk_adjusted_return"):
        va = scores_a.get(key) or 0
        vb = scores_b.get(key) or 0
        if key == "max_drawdown_pct":
            continue
        if va > vb:
            criteria_wins[STRATEGY_A] += 1
        elif vb > va:
            criteria_wins[STRATEGY_B] += 1
        else:
            criteria_wins["tie"] += 1
    if float(agg_a.get("max_drawdown_pct") or 999) < float(agg_b.get("max_drawdown_pct") or 999):
        criteria_wins[STRATEGY_A] += 1
    elif float(agg_b.get("max_drawdown_pct") or 999) < float(agg_a.get("max_drawdown_pct") or 999):
        criteria_wins[STRATEGY_B] += 1

    winner = STRATEGY_A if scores_a["composite_score"] > scores_b["composite_score"] else STRATEGY_B
    if abs(scores_a["composite_score"] - scores_b["composite_score"]) < 3.0:
        winner = "tie"

    return {
        "phase": "28A",
        "strategy_a": {"strategy": STRATEGY_A, "label": "Hybrid B", **scores_a},
        "strategy_b": {"strategy": STRATEGY_B, "label": "Time Exit", **scores_b},
        "criteria_wins": criteria_wins,
        "paired_hybrid_win_pct": hybrid_paired_pct,
        "paired_time_exit_win_pct": time_paired_pct,
        "decision_winner": winner,
        "score_margin": round(abs(scores_a["composite_score"] - scores_b["composite_score"]), 2),
    }


def determine_verdict(
    decision: dict[str, Any],
    paired: dict[str, Any],
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    winner = decision.get("decision_winner")
    margin = float(decision.get("score_margin") or 0)
    hybrid_pct = float(paired.get("hybrid_win_pct") or 0)
    time_pct = float(paired.get("time_exit_win_pct") or 0)

    if winner == "tie" or margin < 3.0:
        if abs(hybrid_pct - time_pct) < 5.0:
            return "NO_STATISTICAL_DIFFERENCE", blockers
        if hybrid_pct > time_pct + 5:
            return "HYBRID_B_IS_BEST", blockers
        if time_pct > hybrid_pct + 5:
            return "TIME_EXIT_IS_BEST", blockers
        return "NO_STATISTICAL_DIFFERENCE", blockers

    if winner == STRATEGY_A:
        return "HYBRID_B_IS_BEST", blockers
    if winner == STRATEGY_B:
        return "TIME_EXIT_IS_BEST", blockers
    return "NO_STATISTICAL_DIFFERENCE", blockers


def build_final_report(
    *,
    verdict: str,
    blockers: list[str],
    decision: dict[str, Any],
    paired: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "28A",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "simulation_only": True,
        "strategy_a": "hybrid_b",
        "strategy_b": "time_exit",
        "decision_winner": decision.get("decision_winner"),
        "score_margin": decision.get("score_margin"),
        "paired_summary": {
            "hybrid_wins": paired.get("hybrid_wins"),
            "time_exit_wins": paired.get("time_exit_wins"),
            "draws": paired.get("draws"),
            "average_dollar_advantage_hybrid": paired.get("average_dollar_advantage_hybrid"),
        },
        "blockers": blockers,
        "conclusion": (
            f"A/B paper validation: {verdict}. "
            f"Decision margin: {decision.get('score_margin')}. "
            f"Paired hybrid wins: {paired.get('hybrid_wins')} vs time_exit: {paired.get('time_exit_wins')}."
        ),
    }
