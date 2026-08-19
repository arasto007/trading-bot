"""Phase 19A — regime split analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.metrics import compute_performance, max_drawdown_r, pf_from_r


def analyze_regimes(trades: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [t for t in trades if t.get("allowed")]
    total_net = sum(float(t["r_multiple"]) for t in accepted)
    total_dd = abs(max_drawdown_r([float(t["r_multiple"]) for t in accepted]))

    regimes: dict[str, Any] = {}
    for regime in ("TREND", "RANGE"):
        subset = [t for t in accepted if str(t.get("regime")) == regime]
        perf = compute_performance(subset)
        net = perf["net_profit_r"]
        dd = abs(perf["maximum_drawdown_r"])
        regimes[regime] = {
            **perf,
            "contribution_to_profit_pct": round(100 * net / total_net, 2) if abs(total_net) > 1e-9 else 0.0,
            "contribution_to_drawdown_pct": round(100 * dd / total_dd, 2) if total_dd > 1e-9 else 0.0,
        }

    other = [t for t in accepted if str(t.get("regime")) not in ("TREND", "RANGE")]
    if other:
        regimes["OTHER"] = compute_performance(other)

    return {
        "phase": "19A",
        "total_trades": len(accepted),
        "total_net_profit_r": round(total_net, 4),
        "regimes": regimes,
    }
