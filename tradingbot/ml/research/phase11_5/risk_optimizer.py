"""Phase 11.5 — risk percent simulation (no RiskGate changes)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase11_5._metrics import scale_trades_risk, trade_metrics

RISK_LEVELS = (0.0025, 0.005, 0.0075, 0.01)


def optimize_risk(trades: list[dict[str, Any]], *, initial_equity: float = 10_000.0) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for risk in RISK_LEVELS:
        scaled = scale_trades_risk(trades, risk, initial_equity=initial_equity)
        m = trade_metrics(scaled, initial_equity=initial_equity)
        final_equity = initial_equity + m["total_pnl"]
        rows.append(
            {
                "risk_percent": risk,
                "final_equity": round(final_equity, 2),
                "return_pct": round((final_equity - initial_equity) / initial_equity * 100, 4),
                "risk_adjusted_return": round(m["expectancy_r"] / max(m["max_drawdown"], 0.01), 4),
                **m,
            }
        )

    best = max(rows, key=lambda x: x.get("risk_adjusted_return", 0), default={})
    current = next((r for r in rows if r["risk_percent"] == 0.005), rows[0] if rows else {})
    return {
        "grid": rows,
        "current_risk": current,
        "best_risk_adjusted": best,
        "recommendation": (
            f"Risk {best.get('risk_percent')} has best risk-adjusted return"
            if best.get("risk_percent") != 0.005
            else "Current 0.5% risk remains optimal on paper data"
        ),
    }
