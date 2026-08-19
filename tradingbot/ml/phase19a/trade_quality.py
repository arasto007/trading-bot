"""Phase 19A — trade quality analysis."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase19a.metrics import expectancy_r, pf_from_r


def analyze_trade_quality(trades: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [t for t in trades if t.get("allowed")]
    if not accepted:
        return {"phase": "19A", "trades": 0, "note": "no_accepted_trades"}

    by_r = sorted(accepted, key=lambda t: float(t["r_multiple"]))
    best = by_r[-10:][::-1]
    worst = by_r[:10]
    r_vals = [float(t["r_multiple"]) for t in accepted]
    threshold_win = float(np.percentile([r for r in r_vals if r > 0], 75)) if any(r > 0 for r in r_vals) else 1.0
    threshold_loss = float(np.percentile([r for r in r_vals if r < 0], 25)) if any(r < 0 for r in r_vals) else -1.0

    large_winners = [t for t in accepted if float(t["r_multiple"]) >= threshold_win]
    large_losers = [t for t in accepted if float(t["r_multiple"]) <= threshold_loss]

    mfe_vals = [float(t.get("mfe", 0)) for t in accepted]
    mae_vals = [float(t.get("mae", 0)) for t in accepted]
    durations = [int(t.get("duration_bars", 0)) for t in accepted]

    exit_quality = round(float(np.mean(mfe_vals)) / max(float(np.mean(mae_vals)), 1e-9), 4)
    holding_quality = round(float(np.mean(durations)), 2)
    risk_efficiency = round(expectancy_r(r_vals) / max(float(np.mean([t.get("risk_percent", 0.005) for t in accepted])), 1e-9), 4)

    return {
        "phase": "19A",
        "trades": len(accepted),
        "best_trades": best,
        "worst_trades": worst,
        "large_winners": {"count": len(large_winners), "threshold_r": threshold_win},
        "large_losers": {"count": len(large_losers), "threshold_r": threshold_loss},
        "exit_quality_mfe_mae_ratio": exit_quality,
        "holding_quality_avg_bars": holding_quality,
        "risk_efficiency": risk_efficiency,
        "pf": pf_from_r(r_vals),
    }
