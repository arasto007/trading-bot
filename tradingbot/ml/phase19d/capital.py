"""Phase 19D — capital simulation certification."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.capital import analyze_capital


def run_capital_simulation(trades: list[dict[str, Any]]) -> dict[str, Any]:
    result = analyze_capital(trades)
    result["phase"] = "19D"
    levels = result.get("levels", {})
    gates = {
        "no_ruin_200": not levels.get("200", {}).get("risk_of_ruin", True),
        "no_ruin_500": not levels.get("500", {}).get("risk_of_ruin", True),
        "no_ruin_1000": not levels.get("1000", {}).get("risk_of_ruin", True),
        "no_ruin_5000": not levels.get("5000", {}).get("risk_of_ruin", True),
    }
    result["gates"] = gates
    result["passed"] = gates["no_ruin_1000"] and gates["no_ruin_500"]
    return result
