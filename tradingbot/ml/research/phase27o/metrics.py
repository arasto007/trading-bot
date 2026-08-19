"""Phase 27O — OOS metrics, generalization gap, Monte Carlo, ranking."""

from __future__ import annotations

import random
import statistics
from typing import Any

from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _profit_factor
from tradingbot.ml.research.phase27a.metrics import _safe_pct
from tradingbot.ml.research.phase27h.stress_engine import apply_execution_delay, subsample_trades
from tradingbot.ml.research.phase27o.window_runner import COMPARE_STRATEGIES

INITIAL_BALANCE = 10_000.0
MC_SEED = 42
HYBRID_B = "hybrid_b"


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _pf_val(pf: Any) -> float | None:
    if isinstance(pf, (int, float)):
        return float(pf)
    return None


def _pseudo_trades(sim_results: list[dict[str, Any]], strategy: str) -> list[dict[str, Any]]:
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
        return {"strategy": strategy, "completed_trades": 0}

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


def build_split_results(
    *,
    split_name: str,
    trades: list[dict[str, Any]],
    sim_results: list[dict[str, Any]],
    per_window: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    strategies = {s: strategy_metrics(trades, sim_results, s) for s in COMPARE_STRATEGIES}
    return {
        "phase": "27O",
        "split": split_name,
        "total_trades": len(trades),
        "strategies": strategies,
        "per_window": per_window or {},
    }


def build_generalization_gap(
    train_results: dict[str, Any],
    validation_results: dict[str, Any],
) -> dict[str, Any]:
    by_strategy: dict[str, Any] = {}
    for strategy in COMPARE_STRATEGIES:
        tr = (train_results.get("strategies") or {}).get(strategy, {})
        va = (validation_results.get("strategies") or {}).get(strategy, {})
        train_pf = _pf_val(tr.get("profit_factor"))
        val_pf = _pf_val(va.get("profit_factor"))
        train_exp = float(tr.get("expectancy") or 0)
        val_exp = float(va.get("expectancy") or 0)
        train_net = float(tr.get("net_profit") or 0)
        val_net = float(va.get("net_profit") or 0)
        train_dd = float(tr.get("max_drawdown_pct") or 0)
        val_dd = float(va.get("max_drawdown_pct") or 0)
        decay = None
        if train_exp != 0:
            decay = round((train_exp - val_exp) / abs(train_exp), 4)
        gap_pf = round((train_pf or 0) - (val_pf or 0), 4) if train_pf is not None and val_pf is not None else None
        gap_exp = round(train_exp - val_exp, 4)
        consistent = (
            val_net > 0
            and (val_pf is None or val_pf >= 1.0)
            and val_exp > 0
        )
        by_strategy[strategy] = {
            "train_profit_factor": tr.get("profit_factor"),
            "validation_profit_factor": va.get("profit_factor"),
            "train_expectancy": train_exp,
            "validation_expectancy": val_exp,
            "train_net_profit": train_net,
            "validation_net_profit": val_net,
            "train_max_drawdown_pct": train_dd,
            "validation_max_drawdown_pct": val_dd,
            "performance_decay": decay,
            "generalization_gap_pf": gap_pf,
            "generalization_gap_expectancy": gap_exp,
            "oos_consistent": consistent,
        }
    hb = by_strategy.get(HYBRID_B, {})
    return {
        "phase": "27O",
        "split_method": "chronological_70_30",
        "by_strategy": by_strategy,
        "hybrid_b_summary": {
            "train_pf": hb.get("train_profit_factor"),
            "validation_pf": hb.get("validation_profit_factor"),
            "train_expectancy": hb.get("train_expectancy"),
            "validation_expectancy": hb.get("validation_expectancy"),
            "performance_decay": hb.get("performance_decay"),
            "oos_consistent": hb.get("oos_consistent"),
        },
    }


def build_oos_metrics(window_splits: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Per-window train/validation metrics for all strategies."""
    windows: dict[str, Any] = {}
    for days, data in sorted(window_splits.items()):
        windows[str(days)] = {
            "train_trades": data.get("train_trade_count"),
            "validation_trades": data.get("val_trade_count"),
            "train": data.get("train_strategies"),
            "validation": data.get("val_strategies"),
        }
    return {"phase": "27O", "windows": windows, "split_fraction_train": 0.70}


def _mc_metrics(trades: list[dict[str, Any]], *, simulations: int = 1000) -> dict[str, Any]:
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


def build_montecarlo_validation(
    val_trades: list[dict[str, Any]],
    val_sim: list[dict[str, Any]],
    *,
    raw_trades: list[dict[str, Any]] | None = None,
    frame: Any = None,
) -> dict[str, Any]:
    rng = random.Random(MC_SEED)
    out: dict[str, Any] = {"phase": "27O", "split": "validation", "strategies": {}}
    for strategy in COMPARE_STRATEGIES:
        strat_trades = [{"pnl": float(r["strategies"][strategy]["pnl"])} for r in val_sim]
        seq = _mc_metrics(strat_trades, simulations=1000)
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
        if strategy == "current_tp_sl" and raw_trades and frame is not None and not getattr(frame, "empty", True):
            d1 = apply_execution_delay(raw_trades, 1, frame, symbol="XAUUSD")
            delay_net = round(sum(float(t["pnl"]) for t in d1), 4)
            fail_nets = []
            for _ in range(100):
                sub = subsample_trades(raw_trades, 0.90, rng)
                fail_nets.append(sum(float(t["pnl"]) for t in sub))
            failure_net = round(statistics.mean(fail_nets), 4)
        out["strategies"][strategy] = {
            "sequence_shuffle": seq,
            "missed_trades": missed,
            "delay_1_bar_baseline_pnl": delay_net,
            "failure_10pct_mean_pnl": failure_net,
        }
    return out


def build_oos_ranking(validation_results: dict[str, Any], generalization: dict[str, Any]) -> dict[str, Any]:
    ranked = []
    for strategy in COMPARE_STRATEGIES:
        m = (validation_results.get("strategies") or {}).get(strategy, {})
        gen = (generalization.get("by_strategy") or {}).get(strategy, {})
        pf = _pf_val(m.get("profit_factor")) or 0.0
        exp = float(m.get("expectancy") or 0)
        dd = float(m.get("max_drawdown_pct") or 0)
        composite = round(pf * 20 + exp * 5 + (10 if gen.get("oos_consistent") else 0) - dd * 0.3, 2)
        ranked.append(
            {
                "strategy": strategy,
                "validation_profit_factor": m.get("profit_factor"),
                "validation_expectancy": exp,
                "validation_net_profit": m.get("net_profit"),
                "validation_max_drawdown_pct": dd,
                "oos_consistent": gen.get("oos_consistent"),
                "performance_decay": gen.get("performance_decay"),
                "composite_score": composite,
            }
        )
    ranked.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, row in enumerate(ranked):
        row["oos_rank"] = i + 1
    return {
        "phase": "27O",
        "ranked": ranked,
        "oos_winner": ranked[0]["strategy"] if ranked else None,
        "hybrid_b_rank": next((r["oos_rank"] for r in ranked if r["strategy"] == HYBRID_B), None),
    }


def build_overfitting_check(generalization: dict[str, Any], ranking: dict[str, Any]) -> dict[str, Any]:
    hb = (generalization.get("by_strategy") or {}).get(HYBRID_B, {})
    val_pf = _pf_val(hb.get("validation_profit_factor"))
    checks = {
        "maintains_profitability": float(hb.get("validation_net_profit") or 0) > 0,
        "maintains_pf": val_pf is None or val_pf >= 1.0,
        "maintains_expectancy": float(hb.get("validation_expectancy") or 0) > 0,
        "drawdown_acceptable": float(hb.get("validation_max_drawdown_pct") or 999) < 50.0,
        "ranks_first_oos": ranking.get("oos_winner") == HYBRID_B,
    }
    return {"phase": "27O", "hybrid_b": checks, "all_pass": all(checks.values())}


def determine_verdict(
    *,
    ranking: dict[str, Any],
    generalization: dict[str, Any],
    overfitting: dict[str, Any],
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    hb = (generalization.get("by_strategy") or {}).get(HYBRID_B, {})
    val_pf = _pf_val(hb.get("validation_profit_factor"))
    val_exp = float(hb.get("validation_expectancy") or 0)
    val_net = float(hb.get("validation_net_profit") or 0)

    if val_net <= 0:
        blockers.append("hybrid_b negative validation net profit")
    if val_pf is not None and val_pf < 1.0:
        blockers.append("hybrid_b validation PF below 1.0")
    if val_exp <= 0:
        blockers.append("hybrid_b validation expectancy non-positive")

    if overfitting.get("all_pass"):
        return "HYBRID_READY_FOR_IMPLEMENTATION", blockers

    if val_net > 0 and val_exp > 0 and ranking.get("hybrid_b_rank", 99) <= 2:
        return "HYBRID_INCONCLUSIVE", blockers

    if val_net <= 0 or (val_pf is not None and val_pf < 0.9):
        return "HYBRID_NOT_GENERALIZING", blockers

    return "HYBRID_INCONCLUSIVE", blockers


def build_final_report(
    *,
    verdict: str,
    blockers: list[str],
    ranking: dict[str, Any],
    generalization: dict[str, Any],
    overfitting: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "27O",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "simulation_only": True,
        "hybrid_under_test": HYBRID_B,
        "split_method": "chronological_70_train_30_validation",
        "oos_winner": ranking.get("oos_winner"),
        "hybrid_b_rank": ranking.get("hybrid_b_rank"),
        "hybrid_b_generalization": generalization.get("hybrid_b_summary"),
        "overfitting_check": overfitting.get("hybrid_b"),
        "blockers": blockers,
        "conclusion": (
            f"OOS winner: {ranking.get('oos_winner')}. "
            f"Hybrid B rank: {ranking.get('hybrid_b_rank')}. Verdict: {verdict}."
        ),
    }
