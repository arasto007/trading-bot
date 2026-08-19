"""Phase 20B — adaptive risk suggestions (research only, not implemented)."""

from __future__ import annotations

from typing import Any


def suggest_adaptive_risk(
    *,
    performance: dict[str, Any],
    drawdown: dict[str, Any],
    capital: dict[str, Any],
    filters: dict[str, Any],
) -> dict[str, Any]:
    """
    Research-only suggestions. DO NOT implement in production.
    """
    overall = performance.get("overall") or {}
    pf = float(overall.get("profit_factor", 0))
    dd = abs(float(drawdown.get("maximum_drawdown_r", 0)))
    streak = int(drawdown.get("worst_loss_streak", 0))
    rec_risk = capital.get("recommended_risk_pct")

    suggestions = [
        {
            "rule": "volatility_scale",
            "description": "Reduce risk by 50% when ADX > 40 or ATR percentile > 80.",
            "rationale": "High volatility amplifies slippage and adverse excursions.",
            "status": "RESEARCH_ONLY",
        },
        {
            "rule": "drawdown_throttle",
            "description": "If equity drawdown exceeds 5%, cut risk to 1% until recovery to peak.",
            "rationale": f"Observed max DD={dd}R; throttle limits cascade losses.",
            "status": "RESEARCH_ONLY",
        },
        {
            "rule": "streak_cooldown",
            "description": "After 3 consecutive losses, pause new entries for 1 hour or skip next signal.",
            "rationale": f"Worst loss streak observed={streak}.",
            "status": "RESEARCH_ONLY",
        },
        {
            "rule": "regime_risk_map",
            "description": "TREND risk 2%, RANGE risk 1.5%, mixed/unknown risk 1%.",
            "rationale": "Regime contribution differs; RANGE historically more stable for phase9_9.",
            "status": "RESEARCH_ONLY",
        },
        {
            "rule": "filter_confidence_gate",
            "description": "When RSI near band edges (40-42 or 58-60), use half risk.",
            "rationale": f"RSI filter class={filters.get('summary', {}).get('rsi')}.",
            "status": "RESEARCH_ONLY",
        },
    ]

    return {
        "phase": "20B",
        "research_only": True,
        "implemented": False,
        "baseline_risk_pct": rec_risk or 0.02,
        "profit_factor_context": pf,
        "suggestions": suggestions,
        "note": "Suggestions must not be applied without a separate approved implementation phase.",
    }
