"""Phase 13.5 — regime routing rules (research only)."""

from __future__ import annotations

from typing import Any

BLOCKED_REGIMES = frozenset({"HIGH_VOLATILITY", "NO_TRADE"})


def route_regime(regime: str) -> str:
    """
    Map Phase 13.2 regime to router action.

    RANGE -> range engine
    TREND -> trend engine
    HIGH_VOLATILITY / NO_TRADE -> BLOCK
    """
    regime = str(regime).upper()
    if regime in BLOCKED_REGIMES:
        return "BLOCK"
    if regime == "RANGE":
        return "RANGE"
    if regime == "TREND":
        return "TREND"
    return "BLOCK"


def route_bar(
    regime: str,
    *,
    range_output: dict[str, Any] | None = None,
    trend_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select active engine output for the current regime."""
    action = route_regime(regime)
    if action == "BLOCK":
        return {
            "action": "BLOCK",
            "regime": regime,
            "source_engine": None,
            "signal": "HOLD",
            "reason": f"regime_{regime.lower()}",
        }
    if action == "RANGE":
        out = range_output or {}
        return {
            "action": "RANGE",
            "regime": regime,
            "source_engine": out.get("engine", "phase9_9"),
            "signal": out.get("signal", "HOLD"),
            "engine_output": out,
        }
    out = trend_output or {}
    return {
        "action": "TREND",
        "regime": regime,
        "source_engine": out.get("engine", "trend_ml"),
        "signal": out.get("signal", "HOLD"),
        "engine_output": out,
    }
