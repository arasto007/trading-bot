"""Performance metrics for counterfactual replays."""

from __future__ import annotations

import math
import statistics
from typing import Any

from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _profit_factor
from tradingbot.ml.research.phase27a.metrics import _safe_pct

INITIAL_BALANCE = 200.0


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def trades_to_pseudo(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "pnl": float(t.get("counterfactual_pnl", t.get("pnl")) or 0),
            "pnl_r": float(t.get("counterfactual_pnl_r", t.get("pnl_r")) or 0),
            "direction": t.get("direction"),
            "timestamp": t.get("timestamp"),
            "exit_timestamp": t.get("exit_timestamp"),
            "duration_bars": t.get("duration_bars"),
        }
        for t in trades
    ]


def compute_metrics(trades: list[dict[str, Any]], *, label: str = "31B") -> dict[str, Any]:
    if not trades:
        return {
            "label": label,
            "trade_count": 0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "net_profit": 0.0,
            "recovery_factor": 0.0,
            "win_rate_pct": 0.0,
            "edge_contribution": 0.0,
        }

    pseudo = trades_to_pseudo(trades)
    pnls = [p["pnl"] for p in pseudo]
    net = sum(pnls)
    eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
    dd_pct, dd_abs = _max_drawdown(eq)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    pf = _profit_factor(pseudo)
    if isinstance(pf, str):
        pf = 999.0

    return {
        "label": label,
        "trade_count": len(trades),
        "profit_factor": round(float(pf), 4) if pf != float("inf") else 999.0,
        "expectancy": round(net / len(trades), 4),
        "sharpe_ratio": round(_sharpe(eq, "M5"), 4),
        "sortino_ratio": round(_sortino(eq, "M5"), 4),
        "max_drawdown_pct": round(dd_pct, 4),
        "max_drawdown_abs": round(dd_abs, 4),
        "net_profit": round(net, 4),
        "recovery_factor": _recovery_factor(net, dd_abs),
        "win_rate_pct": _safe_pct(len(wins), len(pnls)),
        "edge_contribution": round(net, 4),
        "gross_wins": round(sum(wins), 4),
        "gross_losses": round(abs(sum(losses)), 4),
    }


def compare_metrics(baseline: dict, counterfactual: dict) -> dict[str, Any]:
    def delta(key: str) -> float:
        return round(counterfactual.get(key, 0) - baseline.get(key, 0), 4)

    return {
        "isolated_edge_gain": {
            "net_profit": delta("net_profit"),
            "profit_factor": delta("profit_factor"),
            "expectancy": delta("expectancy"),
            "sharpe_ratio": delta("sharpe_ratio"),
            "sortino_ratio": delta("sortino_ratio"),
            "max_drawdown_pct": delta("max_drawdown_pct"),
            "win_rate_pct": delta("win_rate_pct"),
            "trade_count": delta("trade_count"),
        },
        "pct_change": {
            "net_profit_pct": _pct(counterfactual.get("net_profit", 0), baseline.get("net_profit", 0)),
            "profit_factor_pct": _pct(counterfactual.get("profit_factor", 0), baseline.get("profit_factor", 0)),
            "expectancy_pct": _pct(counterfactual.get("expectancy", 0), baseline.get("expectancy", 0)),
        },
    }


def _pct(new: float, old: float) -> float:
    if old == 0:
        return 0.0 if new == 0 else 100.0
    return round((new - old) / abs(old) * 100, 2)


def bootstrap_pf_ci(trades: list[dict[str, Any]], *, n_boot: int = 500, seed: int = 42) -> dict[str, float]:
    """Bootstrap CI for profit factor — research significance proxy."""
    import random

    if len(trades) < 10:
        return {"pf_low": 0.0, "pf_high": 0.0, "confidence": 0.0}

    pnls = [float(t.get("counterfactual_pnl", t.get("pnl")) or 0) for t in trades]
    rng = random.Random(seed)
    pfs = []
    for _ in range(n_boot):
        sample = [rng.choice(pnls) for _ in range(len(pnls))]
        w = sum(p for p in sample if p > 0)
        l = abs(sum(p for p in sample if p < 0))
        pfs.append(w / l if l > 0 else 999.0)
    pfs.sort()
    lo = pfs[int(0.025 * len(pfs))]
    hi = pfs[int(0.975 * len(pfs))]
    return {"pf_low": round(lo, 4), "pf_high": round(hi, 4), "confidence": 95.0}
