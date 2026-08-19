"""Phase 27H — robustness and stress test metrics."""

from __future__ import annotations

import random
import statistics
from collections import defaultdict
from typing import Any

import pandas as pd

from tradingbot.backtest.metrics import _max_drawdown
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _mean, _profit_factor
from tradingbot.ml.research.phase27a.metrics import _regime_norm, _safe_pct
from tradingbot.ml.research.phase27h.stress_engine import (
    MC_SEED,
    apply_execution_delay,
    apply_position_costs,
    apply_slippage_stress,
    apply_spread_stress,
    compute_atr,
    recompute_pnl,
    shuffle_trades,
    subsample_trades,
)

CONFIDENCE_BUCKETS = [
    ("0.50-0.60", 0.50, 0.60),
    ("0.60-0.70", 0.60, 0.70),
    ("0.70-0.80", 0.70, 0.80),
    ("0.80-0.90", 0.80, 0.90),
    ("0.90-1.00", 0.90, 1.01),
]

RUIN_THRESHOLD = 0.50  # 50% of initial balance
INITIAL_BALANCE = 10_000.0


def _metrics(trades: list[dict[str, Any]], *, initial: float = INITIAL_BALANCE) -> dict[str, Any]:
    if not trades:
        return {
            "trade_count": 0,
            "net_profit": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "recovery_factor": 0.0,
        }
    pnls = [float(t["pnl"]) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    net = sum(pnls)
    eq = _equity_curve(trades, initial=initial)
    dd_pct, dd_abs = _max_drawdown(eq)
    recovery = round(net / dd_abs, 4) if dd_abs > 0 else ("inf" if net > 0 else 0.0)
    return {
        "trade_count": len(trades),
        "net_profit": round(net, 4),
        "profit_factor": _profit_factor(trades),
        "expectancy": round(net / len(trades), 4),
        "win_rate_pct": _safe_pct(wins, len(trades)),
        "max_drawdown_pct": round(dd_pct, 4),
        "recovery_factor": recovery,
    }


def _delta(stressed: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "net_profit_delta": round(stressed["net_profit"] - baseline["net_profit"], 4),
        "profit_factor_delta": (
            round(float(stressed["profit_factor"]) - float(baseline["profit_factor"]), 4)
            if isinstance(stressed["profit_factor"], (int, float))
            and isinstance(baseline["profit_factor"], (int, float))
            else None
        ),
        "expectancy_delta": round(stressed["expectancy"] - baseline["expectancy"], 4),
        "win_rate_delta_pct": round(stressed["win_rate_pct"] - baseline["win_rate_pct"], 2),
        "drawdown_delta_pct": round(stressed["max_drawdown_pct"] - baseline["max_drawdown_pct"], 4),
    }


def build_spread_stress(trades: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    scenarios = {}
    for pct in (25, 50, 100):
        stressed_trades = apply_spread_stress(trades, pct)
        m = _metrics(stressed_trades)
        scenarios[f"+{pct}%"] = {**m, "vs_baseline": _delta(m, baseline)}
    return {"phase": "27H", "baseline": baseline, "scenarios": scenarios}


def build_slippage_stress(
    trades: list[dict[str, Any]],
    candles: pd.DataFrame,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    atr = compute_atr(candles)
    scenarios = {}
    for mult in (0.0, 0.25, 0.50, 1.00):
        stressed = apply_slippage_stress(trades, mult, candles, atr)
        m = _metrics(stressed)
        label = f"{mult:.2f}_ATR" if mult > 0 else "0_ATR_baseline"
        scenarios[label] = {**m, "vs_baseline": _delta(m, baseline)}
    return {"phase": "27H", "baseline": baseline, "scenarios": scenarios}


def build_execution_delay_stress(
    trades: list[dict[str, Any]],
    candles: pd.DataFrame,
    baseline: dict[str, Any],
    *,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    scenarios = {}
    for delay in (0, 1, 2, 3):
        stressed = apply_execution_delay(trades, delay, candles, symbol=symbol)
        m = _metrics(stressed)
        scenarios[f"{delay}_candle{'s' if delay != 1 else ''}"] = {**m, "vs_baseline": _delta(m, baseline)}
    return {"phase": "27H", "baseline": baseline, "scenarios": scenarios}


def build_missed_trade_montecarlo(
    trades: list[dict[str, Any]],
    baseline: dict[str, Any],
    *,
    simulations: int = 100,
) -> dict[str, Any]:
    rng = random.Random(MC_SEED)
    levels = (0.05, 0.10, 0.20, 0.30)
    out: dict[str, Any] = {"phase": "27H", "simulations_per_level": simulations, "levels": {}}
    for miss_pct in levels:
        keep = 1.0 - miss_pct
        nets: list[float] = []
        pfs: list[float] = []
        for _ in range(simulations):
            subset = subsample_trades(trades, keep, rng)
            m = _metrics(subset)
            nets.append(m["net_profit"])
            pf = m["profit_factor"]
            if isinstance(pf, (int, float)):
                pfs.append(float(pf))
        nets_sorted = sorted(nets)
        pfs_sorted = sorted(pfs)
        out["levels"][f"{int(miss_pct * 100)}%"] = {
            "miss_pct": miss_pct,
            "median_net_profit": round(statistics.median(nets), 4),
            "worst_net_profit": round(min(nets), 4),
            "best_net_profit": round(max(nets), 4),
            "median_profit_factor": round(statistics.median(pfs), 4) if pfs else 0.0,
            "p10_profit_factor": round(pfs_sorted[max(0, int(len(pfs_sorted) * 0.10) - 1)], 4) if pfs else 0.0,
            "p90_profit_factor": round(pfs_sorted[min(len(pfs_sorted) - 1, int(len(pfs_sorted) * 0.90))], 4) if pfs else 0.0,
            "pct_simulations_profitable": _safe_pct(sum(1 for n in nets if n > 0), len(nets)),
            "vs_baseline_net_delta_median": round(statistics.median(nets) - baseline["net_profit"], 4),
        }
    return out


def build_sequence_montecarlo(
    trades: list[dict[str, Any]],
    baseline: dict[str, Any],
    *,
    simulations: int = 1000,
) -> dict[str, Any]:
    rng = random.Random(MC_SEED + 1)
    max_dds: list[float] = []
    expectancies: list[float] = []
    recoveries: list[float] = []
    ruin_count = 0
    for _ in range(simulations):
        shuffled = shuffle_trades(trades, rng)
        m = _metrics(shuffled)
        expectancies.append(m["expectancy"])
        max_dds.append(m["max_drawdown_pct"])
        rf = m["recovery_factor"]
        recoveries.append(float(rf) if isinstance(rf, (int, float)) else 0.0)
        eq = _equity_curve(shuffled, initial=INITIAL_BALANCE)
        min_eq = min(float(p["equity"]) for p in eq)
        if min_eq < INITIAL_BALANCE * RUIN_THRESHOLD:
            ruin_count += 1

    max_dds_sorted = sorted(max_dds)
    exp_sorted = sorted(expectancies)
    idx95 = min(len(max_dds_sorted) - 1, int(len(max_dds_sorted) * 0.95))
    return {
        "phase": "27H",
        "simulations": simulations,
        "baseline_max_drawdown_pct": baseline["max_drawdown_pct"],
        "max_drawdown_distribution": {
            "mean": round(statistics.mean(max_dds), 4),
            "median": round(statistics.median(max_dds), 4),
            "p95": round(max_dds_sorted[idx95], 4),
            "max": round(max(max_dds), 4),
        },
        "expectancy_distribution": {
            "mean": round(statistics.mean(expectancies), 4),
            "median": round(statistics.median(expectancies), 4),
            "min": round(min(expectancies), 4),
            "max": round(max(expectancies), 4),
        },
        "recovery_factor_distribution": {
            "mean": round(statistics.mean(recoveries), 4),
            "median": round(statistics.median(recoveries), 4),
        },
        "probability_of_ruin_pct": _safe_pct(ruin_count, simulations),
        "ruin_threshold_equity": INITIAL_BALANCE * RUIN_THRESHOLD,
    }


def build_cost_analysis(trades: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    costed = apply_position_costs(trades)
    m = _metrics(costed)
    total_cost = sum(float(t.get("cost_breakdown", {}).get("total", 0)) for t in costed)
    return {
        "phase": "27H",
        "baseline": baseline,
        "after_costs": m,
        "total_costs_applied": round(total_cost, 4),
        "vs_baseline": _delta(m, baseline),
        "cost_model": {
            "spread": "round_trip_from_trade_record",
            "commission_per_lot_round": 7.0,
            "swap_per_lot_per_day": 2.5,
        },
    }


def build_rr_distribution(
    trades: list[dict[str, Any]],
    candles: pd.DataFrame,
) -> dict[str, Any]:
    atr = compute_atr(candles)
    planned = [float(t["rr"]) for t in trades if t.get("rr") is not None]
    realized = [float(t["pnl_r"]) for t in trades if t.get("pnl_r") is not None]
    slip_adj: list[float] = []
    for t in trades:
        bar_idx = int(t.get("bar_index") or 0)
        bar_idx = min(max(bar_idx, 0), len(candles) - 1)
        slip = float(atr.iloc[bar_idx]) * 0.25
        entry = float(t["entry_price"])
        exit_p = float(t["exit_price"])
        sl = t.get("sl")
        direction = str(t["direction"])
        lot = float(t.get("lot") or 0.01)
        sym = str(t.get("symbol") or "XAUUSD")
        if direction == "BUY":
            entry += slip
            exit_p -= slip
        else:
            entry -= slip
            exit_p += slip
        pnl = recompute_pnl(entry_price=entry, exit_price=exit_p, direction=direction, lot=lot, symbol=sym)
        risk = abs(entry - float(sl)) if sl is not None else None
        if risk and risk > 0:
            mult = 1 if direction == "BUY" else -1
            slip_adj.append(round(((exit_p - entry) * mult) / risk, 4))

    def _dist(vals: list[float]) -> dict[str, Any]:
        if not vals:
            return {"count": 0}
        return {
            "count": len(vals),
            "mean": _mean(vals),
            "median": round(statistics.median(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "std_dev": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
        }

    return {
        "phase": "27H",
        "planned_rr": _dist(planned),
        "realized_rr": _dist(realized),
        "slippage_adjusted_rr_0.25_atr": _dist(slip_adj),
        "target_rr": 2.0,
    }


def _confidence_bucket(trades: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {label: [] for label, _, _ in CONFIDENCE_BUCKETS}
    for t in trades:
        c = float(t.get("confidence") or 0.0)
        for label, lo, hi in CONFIDENCE_BUCKETS:
            if lo <= c < hi:
                buckets[label].append(t)
                break
    out: dict[str, Any] = {}
    for label, _, _ in CONFIDENCE_BUCKETS:
        subset = buckets[label]
        m = _metrics(subset)
        out[label] = {
            "trade_count": m["trade_count"],
            "win_rate_pct": m["win_rate_pct"],
            "profit_factor": m["profit_factor"],
            "expectancy": m["expectancy"],
        }
    return out


def build_confidence_robustness(trades: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    baseline_buckets = _confidence_bucket(trades)
    stressed_trades = apply_spread_stress(trades, 50)
    stressed_buckets = _confidence_bucket(stressed_trades)
    return {
        "phase": "27H",
        "baseline_buckets": baseline_buckets,
        "spread_plus_50pct_buckets": stressed_buckets,
        "baseline": baseline,
    }


def build_regime_robustness(
    trades: list[dict[str, Any]],
    candles: pd.DataFrame,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    atr = compute_atr(candles)
    regimes = ["RANGE", "TREND", "TRANSITION"]
    out: dict[str, Any] = {"phase": "27H", "regimes": {}}
    for regime in regimes:
        subset = [t for t in trades if _regime_norm(t.get("regime", "")) == regime]
        base_m = _metrics(subset)
        spread_stress = _metrics(apply_spread_stress(subset, 50)) if subset else _metrics([])
        slip_stress = _metrics(apply_slippage_stress(subset, 0.25, candles, atr)) if subset else _metrics([])
        out["regimes"][regime] = {
            "baseline": base_m,
            "spread_plus_50pct": spread_stress,
            "slippage_0.25_atr": slip_stress,
            "vs_overall_baseline": _delta(base_m, baseline) if subset else None,
        }
    return out


def build_failure_simulation(
    trades: list[dict[str, Any]],
    baseline: dict[str, Any],
    *,
    simulations: int = 100,
) -> dict[str, Any]:
    rng = random.Random(MC_SEED + 2)
    levels = (0.05, 0.10, 0.20)
    out: dict[str, Any] = {"phase": "27H", "simulations_per_level": simulations, "levels": {}}
    for fail_pct in levels:
        keep = 1.0 - fail_pct
        nets: list[float] = []
        pfs: list[float] = []
        dds: list[float] = []
        for _ in range(simulations):
            subset = subsample_trades(trades, keep, rng)
            m = _metrics(subset)
            nets.append(m["net_profit"])
            pf = m["profit_factor"]
            if isinstance(pf, (int, float)):
                pfs.append(float(pf))
            dds.append(m["max_drawdown_pct"])
        out["levels"][f"{int(fail_pct * 100)}%"] = {
            "failure_pct": fail_pct,
            "mean_net_profit": round(statistics.mean(nets), 4),
            "mean_profit_factor": round(statistics.mean(pfs), 4) if pfs else 0.0,
            "mean_max_drawdown_pct": round(statistics.mean(dds), 4),
            "mean_expectancy": round(statistics.mean(nets) / max(len(trades) * keep, 1), 4),
            "pct_simulations_profitable": _safe_pct(sum(1 for n in nets if n > 0), len(nets)),
            "vs_baseline": {
                "net_profit_delta_mean": round(statistics.mean(nets) - baseline["net_profit"], 4),
            },
        }
    return out


def _score_component(value: float, *, good: float, bad: float) -> float:
    if value >= good:
        return 100.0
    if value <= bad:
        return 0.0
    return round(100.0 * (value - bad) / (good - bad), 2)


def build_robustness_score(
    *,
    baseline: dict[str, Any],
    spread: dict[str, Any],
    slippage: dict[str, Any],
    delay: dict[str, Any],
    missed_mc: dict[str, Any],
    sequence_mc: dict[str, Any],
    cost: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    spread50 = spread["scenarios"]["+50%"]
    slip25 = slippage["scenarios"]["0.25_ATR"]
    delay2 = delay["scenarios"]["2_candles"]
    missed10 = missed_mc["levels"]["10%"]
    after_costs = cost["after_costs"]
    fail10 = failure["levels"]["10%"]

    exec_score = statistics.mean(
        [
            _score_component(float(spread50["profit_factor"]), good=1.2, bad=0.9),
            _score_component(float(slip25["profit_factor"]), good=1.2, bad=0.9),
            _score_component(float(delay2["profit_factor"]), good=1.1, bad=0.85),
        ]
    )
    market_score = statistics.mean(
        [
            _score_component(float(spread["scenarios"]["+100%"]["profit_factor"]), good=1.0, bad=0.8),
            _score_component(after_costs["net_profit"], good=500, bad=0),
        ]
    )
    risk_score = statistics.mean(
        [
            _score_component(20 - float(delay2["max_drawdown_pct"]), good=10, bad=0),
            _score_component(float(fail10["mean_profit_factor"]), good=1.2, bad=0.9),
        ]
    )
    mc_score = statistics.mean(
        [
            _score_component(missed10["median_net_profit"], good=800, bad=0),
            _score_component(25 - sequence_mc["max_drawdown_distribution"]["p95"], good=10, bad=0),
            _score_component(100 - sequence_mc["probability_of_ruin_pct"], good=99, bad=90),
        ]
    )
    overall = round(exec_score * 0.30 + market_score * 0.25 + risk_score * 0.20 + mc_score * 0.25, 2)

    return {
        "phase": "27H",
        "execution_robustness": round(exec_score, 2),
        "market_robustness": round(market_score, 2),
        "risk_robustness": round(risk_score, 2),
        "monte_carlo_stability": round(mc_score, 2),
        "overall_robustness": overall,
    }


def determine_verdict(
    *,
    baseline: dict[str, Any],
    scores: dict[str, Any],
    spread: dict[str, Any],
    slippage: dict[str, Any],
    missed_mc: dict[str, Any],
    sequence_mc: dict[str, Any],
    cost: dict[str, Any],
    failure: dict[str, Any],
    trade_count: int,
) -> tuple[str, list[str], list[str]]:
    blockers: list[str] = []
    evidence: list[str] = []

    if trade_count < 200:
        blockers.append(f"trade_count {trade_count} < 200")

    spread50_pf = float(spread["scenarios"]["+50%"]["profit_factor"])
    slip25_pf = float(slippage["scenarios"]["0.25_ATR"]["profit_factor"])
    missed10_median = missed_mc["levels"]["10%"]["median_net_profit"]
    ruin_pct = sequence_mc["probability_of_ruin_pct"]
    cost_net = cost["after_costs"]["net_profit"]
    fail10_pf = float(failure["levels"]["10%"]["mean_profit_factor"])
    overall = scores["overall_robustness"]

    evidence.append(f"baseline PF={baseline['profit_factor']} net={baseline['net_profit']}")
    evidence.append(f"+50% spread PF={spread50_pf} net={spread['scenarios']['+50%']['net_profit']}")
    evidence.append(f"0.25 ATR slippage PF={slip25_pf}")
    evidence.append(f"missed 10% MC median net={missed10_median}")
    evidence.append(f"sequence MC ruin prob={ruin_pct}% p95 DD={sequence_mc['max_drawdown_distribution']['p95']}%")
    evidence.append(f"after costs net={cost_net} overall_score={overall}")

    if spread50_pf < 1.0:
        blockers.append(f"+50% spread PF {spread50_pf} < 1.0")
    if slip25_pf < 1.0:
        blockers.append(f"0.25 ATR slippage PF {slip25_pf} < 1.0")
    if missed10_median <= 0:
        blockers.append("10% missed-trade MC median net <= 0")
    if ruin_pct > 5.0:
        blockers.append(f"sequence MC ruin probability {ruin_pct}% > 5%")
    if cost_net <= 0:
        blockers.append(f"net profit after costs {cost_net} <= 0")
    if fail10_pf < 1.0:
        blockers.append(f"10% failure simulation mean PF {fail10_pf} < 1.0")
    if overall < 55:
        blockers.append(f"overall robustness score {overall} < 55")

    if blockers:
        return "NOT_ROBUST_FOR_PAPER", blockers, evidence
    return "ROBUST_FOR_PAPER", blockers, evidence


def build_final_report(
    *,
    baseline: dict[str, Any],
    baseline_source: dict[str, Any],
    scores: dict[str, Any],
    spread: dict[str, Any],
    slippage: dict[str, Any],
    missed_mc: dict[str, Any],
    sequence_mc: dict[str, Any],
    cost: dict[str, Any],
    failure: dict[str, Any],
    trade_count: int,
) -> dict[str, Any]:
    verdict, blockers, evidence = determine_verdict(
        baseline=baseline,
        scores=scores,
        spread=spread,
        slippage=slippage,
        missed_mc=missed_mc,
        sequence_mc=sequence_mc,
        cost=cost,
        failure=failure,
        trade_count=trade_count,
    )
    return {
        "phase": "27H",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "input_source": "phase27f_repaired_replay",
        "baseline_source": "phase27g",
        "completed_trades": trade_count,
        "baseline_metrics": baseline,
        "phase27g_baseline": baseline_source,
        "robustness_scores": scores,
        "blockers": blockers,
        "evidence": evidence,
        "critical_stress_summary": {
            "spread_plus_50pct_pf": spread["scenarios"]["+50%"]["profit_factor"],
            "slippage_0.25_atr_pf": slippage["scenarios"]["0.25_ATR"]["profit_factor"],
            "missed_10pct_median_net": missed_mc["levels"]["10%"]["median_net_profit"],
            "sequence_ruin_prob_pct": sequence_mc["probability_of_ruin_pct"],
            "after_costs_net": cost["after_costs"]["net_profit"],
            "failure_10pct_mean_pf": failure["levels"]["10%"]["mean_profit_factor"],
        },
        "conclusion": (
            "Strategy remains profitable under moderate execution degradation."
            if verdict == "ROBUST_FOR_PAPER"
            else "Strategy degrades materially under realistic execution stress."
        ),
    }
