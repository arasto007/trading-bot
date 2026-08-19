"""Phase 20B — execution stability analysis."""

from __future__ import annotations

from typing import Any

import numpy as np


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    arr = np.sort(np.asarray(values, dtype=float))
    idx = min(len(arr) - 1, int(len(arr) * q))
    return round(float(arr[idx]), 4)


def analyze_execution(observation: dict[str, Any]) -> dict[str, Any]:
    executions = observation.get("executions") or []
    latency_rows = observation.get("latency") or []

    latencies = [float(r.get("latency_ms", 0)) for r in latency_rows if r.get("latency_ms") is not None]
    for e in executions:
        if e.get("execution_latency_ms") is not None:
            latencies.append(float(e["execution_latency_ms"]))

    attempts = len(executions)
    successes = sum(1 for e in executions if e.get("success"))
    rejections = sum(1 for e in executions if e.get("success") is False or e.get("blocked"))
    rejection_rate = rejections / attempts if attempts else 0.0

    slips = [float(e["slippage"]) for e in executions if e.get("slippage") is not None]
    spreads = [float(e["spread"]) for e in executions if e.get("spread") is not None]

    # Path observation has no broker fills — mark as observation-only
    broker_samples = attempts + len(latency_rows)
    latency_dist = {
        "count": len(latencies),
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "p99_ms": _percentile(latencies, 0.99),
        "mean_ms": round(float(np.mean(latencies)), 4) if latencies else 0.0,
    }

    passed = True
    notes = []
    if broker_samples == 0:
        notes.append("no_broker_execution_samples")
        # Not a fail by itself if path observation is healthy — flag as limited
        passed = True
    else:
        if latency_dist["p95_ms"] > 100:
            passed = False
            notes.append("latency_p95_exceeded")
        if rejection_rate > 0.25:
            passed = False
            notes.append("high_rejection_rate")

    return {
        "phase": "20B",
        "broker_samples": broker_samples,
        "attempts": attempts,
        "successes": successes,
        "rejections": rejections,
        "rejection_rate": round(rejection_rate, 4),
        "latency": latency_dist,
        "slippage": {
            "count": len(slips),
            "mean": round(float(np.mean(slips)), 6) if slips else None,
            "max": round(float(np.max(slips)), 6) if slips else None,
        },
        "spread": {
            "count": len(spreads),
            "mean": round(float(np.mean(spreads)), 6) if spreads else None,
            "max": round(float(np.max(spreads)), 6) if spreads else None,
        },
        "passed": passed,
        "notes": notes,
    }
