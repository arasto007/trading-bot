"""Phase 20B — live performance analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.metrics import compute_performance


def _r_vals(trades: list[dict[str, Any]]) -> list[float]:
    out = []
    for t in trades:
        if "r_multiple" in t:
            out.append(float(t["r_multiple"]))
        elif "pnl_r" in t:
            out.append(float(t["pnl_r"]))
        elif t.get("success") is True:
            out.append(1.0)
        elif t.get("success") is False:
            out.append(-1.0)
    return out


def analyze_live_performance(observation: dict[str, Any]) -> dict[str, Any]:
    trades = observation.get("trades") or []
    # Normalize allowed flag for compute_performance
    norm = []
    for t in trades:
        row = dict(t)
        row.setdefault("allowed", True)
        if "r_multiple" not in row and "pnl_r" in row:
            row["r_multiple"] = row["pnl_r"]
        if "r_multiple" not in row:
            continue
        norm.append(row)

    overall = compute_performance(norm) if norm else compute_performance([])
    wins = [t for t in norm if float(t.get("r_multiple", 0)) > 0]
    losses = [t for t in norm if float(t.get("r_multiple", 0)) < 0]

    regimes: dict[str, Any] = {}
    for regime in ("TREND", "RANGE"):
        subset = [t for t in norm if str(t.get("regime", "")).upper() == regime]
        regimes[regime] = compute_performance(subset) if subset else {"trades": 0}

    mixed = [t for t in norm if str(t.get("regime", "")).upper() not in ("TREND", "RANGE")]
    regimes["MIXED"] = compute_performance(mixed) if mixed else {"trades": 0}

    return {
        "phase": "20B",
        "data_source": observation.get("data_source"),
        "overall": overall,
        "winning_trades": {
            "count": len(wins),
            "avg_r": overall.get("average_win_r"),
            "share": round(len(wins) / max(len(norm), 1), 4),
        },
        "losing_trades": {
            "count": len(losses),
            "avg_r": overall.get("average_loss_r"),
            "share": round(len(losses) / max(len(norm), 1), 4),
        },
        "by_regime": regimes,
        "trades_observed": len(norm),
    }
