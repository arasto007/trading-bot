"""Phase 20C — broker quality aggregation."""

from __future__ import annotations

from typing import Any


def analyze_broker_quality(
    data: dict[str, Any],
    *,
    slippage: dict[str, Any],
    spread: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    all_exec = data.get("all_executions") or []
    fills = data.get("real_fills") or []

    if not fills and not all_exec:
        return {
            "phase": "20C",
            "status": "PENDING",
            "reason": "no_broker_activity",
        }

    failures = sum(1 for e in all_exec if e.get("success") is False)
    rejected = sum(
        1 for e in all_exec
        if e.get("blocked") or "reject" in str(e.get("message", "")).lower()
    )
    partial = sum(1 for e in all_exec if e.get("partial_fill") or e.get("partial"))
    attempts = max(len(all_exec), len(fills))

    return {
        "phase": "20C",
        "status": "COMPLETE" if fills else "PARTIAL",
        "average_spread": spread.get("average_spread"),
        "maximum_spread": spread.get("maximum_spread"),
        "spread_spikes": spread.get("spread_spikes"),
        "average_slippage": slippage.get("average_slippage"),
        "worst_slippage": slippage.get("worst_slippage"),
        "execution_failures": failures,
        "rejected_orders": rejected,
        "partial_fills": partial,
        "attempts": attempts,
        "successful_fills": len(fills),
        "failure_rate": round(failures / attempts, 4) if attempts else None,
    }
