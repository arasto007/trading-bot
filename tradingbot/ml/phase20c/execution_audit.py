"""Phase 20C — real execution audit."""

from __future__ import annotations

from typing import Any

import numpy as np


def audit_broker_execution(data: dict[str, Any]) -> dict[str, Any]:
    fills = data.get("real_fills") or []
    all_exec = data.get("all_executions") or []

    if not fills and not all_exec:
        return {
            "phase": "20C",
            "status": "PENDING",
            "reason": "no_broker_execution_records",
            "orders_analyzed": 0,
            "orders": [],
        }

    orders = []
    for e in fills:
        requested = e.get("requested_price", e.get("entry", e.get("price")))
        fill = e.get("fill_price", e.get("entry", e.get("price")))
        slip = e.get("slippage")
        if slip is None and requested is not None and fill is not None:
            try:
                slip = abs(float(fill) - float(requested))
            except (TypeError, ValueError):
                slip = None
        orders.append({
            "timestamp": e.get("timestamp"),
            "symbol": e.get("symbol"),
            "direction": e.get("direction"),
            "order_type": e.get("order_type", "MARKET"),
            "requested_price": requested,
            "fill_price": fill,
            "slippage": slip,
            "spread": e.get("spread"),
            "execution_delay_ms": e.get("execution_latency_ms", e.get("latency_ms")),
            "ticket": e.get("ticket"),
            "volume": e.get("volume"),
            "success": e.get("success", True),
            "fill_quality": _fill_quality(slip, e.get("spread")),
        })

    slips = [float(o["slippage"]) for o in orders if o.get("slippage") is not None]
    delays = [float(o["execution_delay_ms"]) for o in orders if o.get("execution_delay_ms") is not None]

    return {
        "phase": "20C",
        "status": "COMPLETE" if orders else "PENDING",
        "orders_analyzed": len(orders),
        "orders": orders[:500],
        "summary": {
            "mean_slippage": round(float(np.mean(slips)), 6) if slips else None,
            "max_slippage": round(float(np.max(slips)), 6) if slips else None,
            "mean_delay_ms": round(float(np.mean(delays)), 2) if delays else None,
            "fill_quality_distribution": _quality_dist(orders),
        },
    }


def _fill_quality(slippage: Any, spread: Any) -> str:
    try:
        s = float(slippage) if slippage is not None else None
    except (TypeError, ValueError):
        s = None
    if s is None:
        return "UNKNOWN"
    if s <= 0:
        return "EXCELLENT"
    if s < 0.5:
        return "GOOD"
    if s < 1.5:
        return "FAIR"
    return "POOR"


def _quality_dist(orders: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for o in orders:
        q = o.get("fill_quality", "UNKNOWN")
        dist[q] = dist.get(q, 0) + 1
    return dist
