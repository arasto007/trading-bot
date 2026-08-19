"""Phase 13.6 — session-based performance analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import phase13_6_reports_dir
from tradingbot.ml.research.phase11_5._metrics import trade_metrics
from tradingbot.ml.research.phase11_5.session_optimizer import SESSION_WINDOWS, optimize_sessions

SESSION_LABELS: dict[str, str] = {
    "asia": "Asia",
    "london": "London",
    "new_york": "New York",
}


def optimize_router_sessions(trades: list[dict[str, Any]], *, base_dir: str | Path | None = None) -> dict[str, Any]:
    executed = [t for t in trades if t.get("type") == "trade"]
    result = optimize_sessions(executed)
    sessions = []
    for row in result.get("sessions", []):
        key = str(row.get("session", ""))
        sessions.append(
            {
                "session": SESSION_LABELS.get(key, key),
                "session_key": key,
                "trades": row.get("trades", 0),
                "profit_factor": row.get("profit_factor", 0.0),
                "win_rate": row.get("win_rate", 0.0),
                "expectancy": row.get("expectancy_r", 0.0),
                "max_drawdown": row.get("max_drawdown", 0.0),
            }
        )

    best_sessions = {
        "generated_at_utc": pd.Timestamp.utcnow().isoformat(),
        "sessions": sessions,
        "recommended_windows": result.get("recommended_windows", []),
        "best_pf_session": result.get("best_pf_session", {}),
        "best_expectancy_session": result.get("best_expectancy_session", {}),
    }
    out_dir = phase13_6_reports_dir(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "best_sessions.json").write_text(json.dumps(best_sessions, indent=2), encoding="utf-8")
    return best_sessions


def session_filter_for_names(names: list[str]):
    allowed = {n.lower() for n in names}

    def _filter(ts: pd.Timestamp) -> bool:
        hour = pd.Timestamp(ts).hour
        for name in allowed:
            if name in SESSION_WINDOWS:
                start, end = SESSION_WINDOWS[name]
                if start <= hour < end:
                    return True
        return False

    return _filter
