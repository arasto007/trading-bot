"""Phase 20C — end-to-end latency analysis."""

from __future__ import annotations

from typing import Any

import numpy as np


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    arr = np.sort(np.asarray(values, dtype=float))
    idx = min(len(arr) - 1, int(len(arr) * q))
    return round(float(arr[idx]), 4)


def analyze_latency(data: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    latency_rows = data.get("latency") or []
    orders = audit.get("orders") or []

    signal_ms = [float(r["latency_ms"]) for r in latency_rows if r.get("latency_ms") is not None]
    exec_ms = [
        float(o["execution_delay_ms"])
        for o in orders
        if o.get("execution_delay_ms") is not None
    ]
    # RiskGate / broker confirmation not separately instrumented in Phase 20A —
    # report as pending when missing
    risk_ms: list[float] = []
    broker_ms: list[float] = []
    for e in data.get("all_executions") or []:
        if e.get("risk_latency_ms") is not None:
            risk_ms.append(float(e["risk_latency_ms"]))
        if e.get("broker_confirm_ms") is not None:
            broker_ms.append(float(e["broker_confirm_ms"]))

    total = []
    for s, e in zip(signal_ms, exec_ms):
        total.append(s + e)
    if not total and signal_ms:
        total = list(signal_ms)
    if not total and exec_ms:
        total = list(exec_ms)

    if not signal_ms and not exec_ms:
        return {
            "phase": "20C",
            "status": "PENDING",
            "reason": "no_latency_samples",
            "stages": {
                "signal_generation": {"status": "PENDING"},
                "riskgate": {"status": "PENDING"},
                "execution": {"status": "PENDING"},
                "broker_confirmation": {"status": "PENDING"},
                "end_to_end": {"status": "PENDING"},
            },
        }

    def stage(vals: list[float], name: str) -> dict[str, Any]:
        if not vals:
            return {"status": "PENDING", "stage": name, "count": 0}
        return {
            "status": "COMPLETE",
            "stage": name,
            "count": len(vals),
            "p50_ms": _pct(vals, 0.50),
            "p95_ms": _pct(vals, 0.95),
            "p99_ms": _pct(vals, 0.99),
            "mean_ms": round(float(np.mean(vals)), 4),
        }

    return {
        "phase": "20C",
        "status": "COMPLETE",
        "stages": {
            "signal_generation": stage(signal_ms, "signal_generation"),
            "riskgate": stage(risk_ms, "riskgate"),
            "execution": stage(exec_ms, "execution"),
            "broker_confirmation": stage(broker_ms, "broker_confirmation"),
            "end_to_end": stage(total, "end_to_end"),
        },
    }
