"""Phase 20C — broker validation verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase20c.config import MIN_REAL_TRADES, VERDICTS


def determine_verdict(
    *,
    data: dict[str, Any],
    risk: dict[str, Any],
    stability: dict[str, Any],
    score: dict[str, Any],
) -> str:
    """LIVE_VALIDATED only with sufficient real broker fills and passing gates."""
    if not data.get("has_sufficient_trades"):
        return "WAITING_FOR_REAL_TRADES"

    if score.get("status") != "COMPLETE":
        return "WAITING_FOR_REAL_TRADES"

    if not risk.get("passed", False):
        return "WAITING_FOR_REAL_TRADES"

    if not stability.get("passed", False):
        return "WAITING_FOR_REAL_TRADES"

    if not score.get("meets_threshold", False):
        return "WAITING_FOR_REAL_TRADES"

    return "LIVE_VALIDATED"


def build_final_report(
    *,
    verdict: str,
    data: dict[str, Any],
    audit: dict[str, Any],
    slippage: dict[str, Any],
    spread: dict[str, Any],
    latency: dict[str, Any],
    sim_vs_live: dict[str, Any],
    risk: dict[str, Any],
    stability: dict[str, Any],
    broker_quality: dict[str, Any],
    score: dict[str, Any],
) -> dict[str, Any]:
    pending = []
    for name, report in (
        ("broker_execution", audit),
        ("slippage", slippage),
        ("spread", spread),
        ("latency", latency),
        ("simulation_vs_live", sim_vs_live),
        ("risk_validation", risk),
        ("system_stability", stability),
        ("final_live_score", score),
    ):
        if report.get("status") in ("PENDING", "PARTIAL") or report.get("status") is None:
            if verdict == "WAITING_FOR_REAL_TRADES":
                pending.append(name)

    return {
        "phase": "20C",
        "verdict": verdict,
        "verdicts_allowed": list(VERDICTS),
        "read_only": True,
        "production_modified": False,
        "real_fill_count": data.get("real_fill_count", 0),
        "min_required_trades": MIN_REAL_TRADES,
        "has_sufficient_trades": data.get("has_sufficient_trades"),
        "pending_analyses": pending if verdict == "WAITING_FOR_REAL_TRADES" else [],
        "files_present": data.get("files_present"),
        "score": score,
        "risk_passed": risk.get("passed"),
        "stability_passed": stability.get("passed"),
        "broker_quality": {
            "status": broker_quality.get("status"),
            "successful_fills": broker_quality.get("successful_fills"),
            "failure_rate": broker_quality.get("failure_rate"),
        },
        "recommendation": {
            "WAITING_FOR_REAL_TRADES": (
                "No sufficient real broker fills yet. Continue Phase 20A live deployment "
                f"until at least {MIN_REAL_TRADES} successful executions are logged, then re-run Phase 20C."
            ),
            "LIVE_VALIDATED": (
                "Real broker executions validated — execution quality, risk, and stability gates passed."
            ),
        }.get(verdict, ""),
    }
