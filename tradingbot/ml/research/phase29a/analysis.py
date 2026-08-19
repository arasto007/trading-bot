"""Winner vs loser analysis and filter threshold simulation."""

from __future__ import annotations

import statistics
from typing import Any

from tradingbot.accounting.metrics import compute_performance_metrics
from tradingbot.accounting.ledger import AccountingLedger, ClosedTradeRecord
from tradingbot.ml.research.phase26b.analyzers import _profit_factor


COMPARE_FIELDS = [
    "rsi", "adx", "atr", "atr_percentile", "spread", "volume_percentile",
    "ema20_distance_pct", "ema50_distance_pct", "market_structure_hh",
    "market_structure_ll", "range_compression", "confidence", "sl_atr_multiple",
    "mfe", "mae", "duration_bars", "quality_score", "false_signal_score",
    "context_score", "signal_filter_score",
]


def _mean(vals: list[float]) -> float:
    return statistics.mean(vals) if vals else 0.0


def winner_vs_loser_analysis(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    winners = [e for e in enriched if e.get("is_winner")]
    losers = [e for e in enriched if not e.get("is_winner") and float(e.get("pnl", 0)) < 0]

    comparisons: dict[str, Any] = {}
    for field in COMPARE_FIELDS:
        w_vals = [float(e.get(field, 0)) for e in winners if e.get(field) is not None]
        l_vals = [float(e.get(field, 0)) for e in losers if e.get(field) is not None]
        if not w_vals or not l_vals:
            continue
        w_mean, l_mean = _mean(w_vals), _mean(l_vals)
        diff = w_mean - l_mean
        pooled = statistics.pstdev(w_vals + l_vals) or 1.0
        effect = abs(diff) / pooled
        significant = effect > 0.2 and abs(diff) > 0.01 * max(abs(w_mean), abs(l_mean), 1)
        comparisons[field] = {
            "winner_mean": round(w_mean, 4),
            "loser_mean": round(l_mean, 4),
            "difference": round(diff, 4),
            "effect_size": round(effect, 4),
            "statistically_significant": significant,
        }

    categorical = {}
    for field in ("session", "regime", "engine", "direction", "swing_position"):
        w_counts: dict[str, int] = {}
        l_counts: dict[str, int] = {}
        for e in winners:
            k = str(e.get(field, "unknown"))
            w_counts[k] = w_counts.get(k, 0) + 1
        for e in losers:
            k = str(e.get(field, "unknown"))
            l_counts[k] = l_counts.get(k, 0) + 1
        categorical[field] = {"winners": w_counts, "losers": l_counts}

    sig = [k for k, v in comparisons.items() if v.get("statistically_significant")]
    return {
        "phase": "29A",
        "winner_count": len(winners),
        "loser_count": len(losers),
        "numeric_comparisons": comparisons,
        "categorical_comparisons": categorical,
        "significant_differentiators": sig,
        "top_insights": [
            f"{k}: winners={comparisons[k]['winner_mean']}, losers={comparisons[k]['loser_mean']}"
            for k in sig[:8]
        ],
    }


def build_signal_filter_score(enriched: list[dict[str, Any]]) -> list[float]:
    """Estimate winner-population membership from causal features only."""
    winners = [e for e in enriched if e.get("is_winner")]
    if not winners:
        return [50.0] * len(enriched)

    w_adx = _mean([float(e.get("adx", 0)) for e in winners])
    w_conf = _mean([float(e.get("confidence", 0)) for e in winners])
    w_false = _mean([float(e.get("false_signal_score", 50)) for e in winners])
    w_ctx = _mean([float(e.get("context_score", 50)) for e in winners])
    w_trend = sum(1 for e in winners if e.get("trend_aligned")) / len(winners)

    scores: list[float] = []
    for e in enriched:
        s = 0.0
        adx = float(e.get("adx", 0))
        conf = float(e.get("confidence", 0))
        false_s = float(e.get("false_signal_score", 0))
        ctx = float(e.get("context_score", 50))
        aligned = 1.0 if e.get("trend_aligned") else 0.0

        s += 25 * min(1, adx / max(w_adx, 1))
        s += 20 * min(1, conf / max(w_conf, 0.01))
        s += 20 * (1 - false_s / 100)
        s += 20 * min(1, ctx / max(w_ctx, 1))
        s += 15 * (1 if aligned >= w_trend else 0.5)
        scores.append(round(max(0, min(100, s)), 2))
    return scores


def _trades_to_perf(trades: list[dict[str, Any]], *, initial: float = 200.0) -> dict[str, Any]:
    ledger = AccountingLedger(initial_balance=initial)
    for t in trades:
        ledger.apply_close(
            ClosedTradeRecord(
                trade_id=str(t.get("trade_id", "")),
                timestamp=str(t.get("timestamp", "")),
                exit_timestamp=str(t.get("exit_timestamp", "")),
                symbol=str(t.get("symbol", "XAUUSD")),
                direction=str(t.get("direction", "SELL")),
                entry_price=float(t.get("entry_price", 0)),
                exit_price=float(t.get("exit_price", 0)),
                lot=float(t.get("lot", 0.01)),
                pnl=float(t.get("pnl", 0)),
                pnl_r=float(t.get("pnl_r", 0)),
            )
        )
    return compute_performance_metrics(ledger)


def simulate_filter_cutoffs(
    trades: list[dict[str, Any]],
    scores: list[float],
    *,
    initial: float = 200.0,
) -> dict[str, Any]:
    baseline = _trades_to_perf(trades, initial=initial)
    results = []
    for pct in (5, 10, 15, 20, 25):
        cutoff_idx = int(len(scores) * pct / 100)
        threshold = sorted(scores)[cutoff_idx] if cutoff_idx < len(scores) else 0
        kept = [t for t, s in zip(trades, scores) if s >= threshold]
        if not kept:
            continue
        perf = _trades_to_perf(kept, initial=initial)
        results.append({
            "remove_bottom_pct": pct,
            "threshold_score": threshold,
            "trade_count": len(kept),
            "net_profit": perf.get("net_profit"),
            "profit_factor": perf.get("profit_factor"),
            "expectancy": perf.get("expectancy"),
            "max_drawdown_pct": perf.get("max_drawdown_pct"),
            "sharpe_ratio": perf.get("sharpe_ratio"),
            "recovery_factor": perf.get("recovery_factor"),
            "win_rate_pct": perf.get("win_rate_pct"),
        })
    optimal = None
    for r in results:
        if r["trade_count"] < 300:
            continue
        pf = float(r["profit_factor"]) if isinstance(r["profit_factor"], (int, float)) else 0
        base_pf = float(baseline["profit_factor"]) if isinstance(baseline["profit_factor"], (int, float)) else 1
        if pf >= base_pf * 1.1:
            if optimal is None or pf > float(optimal.get("profit_factor", 0)):
                optimal = r
    return {
        "phase": "29A",
        "baseline": baseline,
        "cutoff_results": results,
        "optimal_cutoff": optimal,
    }
