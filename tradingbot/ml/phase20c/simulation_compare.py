"""Phase 20C — simulation vs real execution comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase19a.metrics import compute_performance


def _load_phase20b_performance(base_dir: str | Path | None = None) -> dict[str, Any] | None:
    from tradingbot.ml.data.paths import reports_dir as _r

    path = _r(base_dir) / "phase20b" / "live_performance.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def compare_simulation_vs_live(
    data: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    fills = data.get("real_fills") or []
    if not fills:
        return {
            "phase": "20C",
            "status": "PENDING",
            "reason": "no_real_fills_for_comparison",
            "simulation": None,
            "live": None,
            "delta": None,
        }

    # Build live trade metrics from fills when R-multiples present
    live_trades = []
    for f in fills:
        r = f.get("r_multiple", f.get("pnl_r"))
        if r is None:
            continue
        live_trades.append({"allowed": True, "r_multiple": float(r)})

    live_perf = compute_performance(live_trades) if live_trades else None

    sim_report = _load_phase20b_performance(base_dir)
    sim_perf = (sim_report or {}).get("overall") if sim_report else None

    if live_perf is None:
        return {
            "phase": "20C",
            "status": "PENDING",
            "reason": "real_fills_lack_pnl_r_multiples",
            "real_fill_count": len(fills),
            "simulation": sim_perf,
            "live": None,
            "delta": None,
        }

    delta = None
    if sim_perf:
        delta = {
            "profit_factor": round(
                float(live_perf.get("profit_factor", 0)) - float(sim_perf.get("profit_factor", 0)), 4
            ),
            "expectancy_r": round(
                float(live_perf.get("expectancy_r", 0)) - float(sim_perf.get("expectancy_r", 0)), 4
            ),
            "maximum_drawdown_r": round(
                float(live_perf.get("maximum_drawdown_r", 0))
                - float(sim_perf.get("maximum_drawdown_r", 0)),
                4,
            ),
            "win_rate": round(
                float(live_perf.get("win_rate", 0)) - float(sim_perf.get("win_rate", 0)), 4
            ),
            "net_profit_r": round(
                float(live_perf.get("net_profit_r", 0)) - float(sim_perf.get("net_profit_r", 0)), 4
            ),
        }

    return {
        "phase": "20C",
        "status": "COMPLETE",
        "simulation": sim_perf,
        "live": live_perf,
        "delta": delta,
        "real_fill_count": len(fills),
    }
