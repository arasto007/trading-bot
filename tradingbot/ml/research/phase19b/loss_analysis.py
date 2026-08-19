"""Phase 19B — losing trade cluster analysis."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def _bucket(values: list[float], n: int = 4) -> list[str]:
    if not values:
        return []
    qs = np.quantile(values, np.linspace(0, 1, n + 1))
    labels = []
    for v in values:
        for i in range(n):
            if v <= qs[i + 1] or i == n - 1:
                labels.append(f"q{i + 1}")
                break
    return labels


def _cluster_rate(trades: list[dict], key: str, *, continuous: bool = False) -> dict[str, Any]:
    if continuous:
        vals = [float(t.get(key, 0) or 0) for t in trades]
        labels = _bucket(vals)
        groups: dict[str, list[float]] = defaultdict(list)
        for t, lab in zip(trades, labels):
            groups[lab].append(float(t["r_multiple"]))
    else:
        groups = defaultdict(list)
        for t in trades:
            groups[str(t.get(key, "unknown"))].append(float(t["r_multiple"]))

    out = {}
    for k, rs in groups.items():
        losses = sum(1 for r in rs if r < 0)
        out[k] = {
            "trades": len(rs),
            "losses": losses,
            "loss_rate": round(losses / max(len(rs), 1), 4),
            "net_r": round(sum(rs), 4),
        }
    # rank by loss rate * count
    ranked = sorted(out.items(), key=lambda x: (-x[1]["loss_rate"], -x[1]["losses"]))
    return {"by_value": dict(ranked), "worst": ranked[0][0] if ranked else None}


def analyze_losses(trades: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [t for t in trades if t.get("is_loss")]
    wins = [t for t in trades if t.get("is_win")]
    all_t = trades

    dimensions = {
        "regime": _cluster_rate(all_t, "regime"),
        "hour": _cluster_rate(all_t, "hour"),
        "weekday": _cluster_rate(all_t, "weekday"),
        "session": _cluster_rate(all_t, "session"),
        "adx": _cluster_rate(all_t, "adx", continuous=True),
        "atr": _cluster_rate(all_t, "atr", continuous=True),
        "rsi": _cluster_rate(all_t, "rsi", continuous=True),
        "spread": _cluster_rate(all_t, "spread", continuous=True),
        "confidence": _cluster_rate(all_t, "confidence", continuous=True),
        "quality_score": _cluster_rate(all_t, "quality_score", continuous=True),
        "risk_percent": _cluster_rate(all_t, "risk_percent", continuous=True),
        "duration_bars": _cluster_rate(all_t, "duration_bars", continuous=True),
        "sl_distance": _cluster_rate(all_t, "sl_distance", continuous=True),
        "tp_distance": _cluster_rate(all_t, "tp_distance", continuous=True),
        "trend_age": _cluster_rate(all_t, "trend_age", continuous=True),
    }

    patterns = []
    for dim, block in dimensions.items():
        worst = block.get("worst")
        if worst is None:
            continue
        info = block["by_value"].get(worst, {})
        if info.get("loss_rate", 0) >= 0.55 and info.get("trades", 0) >= 5:
            patterns.append({
                "dimension": dim,
                "bucket": worst,
                "loss_rate": info["loss_rate"],
                "trades": info["trades"],
                "net_r": info["net_r"],
            })
    patterns.sort(key=lambda p: (-p["loss_rate"], -p["trades"]))

    return {
        "phase": "19B",
        "losing_trades": len(losses),
        "winning_trades": len(wins),
        "total_trades": len(all_t),
        "loss_rate": round(len(losses) / max(len(all_t), 1), 4),
        "mean_loss_r": round(float(np.mean([t["r_multiple"] for t in losses])), 4) if losses else 0.0,
        "clusters": dimensions,
        "recurring_patterns": patterns[:15],
    }
