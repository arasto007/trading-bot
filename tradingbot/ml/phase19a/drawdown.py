"""Phase 19A — drawdown analysis."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase14_8.drawdown_analyzer import analyze_drawdown


def analyze_drawdown_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [t for t in trades if t.get("allowed")]
    base = analyze_drawdown(accepted)

    r_vals = [float(t["r_multiple"]) for t in accepted]
    equity = np.cumsum(r_vals) if r_vals else np.array([])
    underwater = 0
    if len(equity):
        peak = np.maximum.accumulate(equity)
        underwater = int(np.sum(equity < peak))

    return {
        "phase": "19A",
        **base,
        "underwater_trades": underwater,
        "underwater_pct": round(underwater / max(len(r_vals), 1), 4),
        "trades": len(accepted),
    }
