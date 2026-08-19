"""Tick and execution schema validation."""

from __future__ import annotations

from typing import Any

TICK_REQUIRED = {"symbol", "timestamp_ms", "bid", "ask", "spread_points", "collector_seq"}
EXECUTION_REQUIRED = {
    "execution_id",
    "symbol",
    "direction",
    "leg",
    "requested_price",
    "fill_price",
    "retcode",
    "local_send_monotonic_ns",
    "timestamp_send_ms",
    "timestamp_fill_ms",
    "execution_delay_ms",
}


def validate_tick_row(row: dict[str, Any]) -> list[str]:
    errors = []
    missing = TICK_REQUIRED - set(row.keys())
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
    if row.get("bid") is not None and row.get("ask") is not None:
        if float(row["bid"]) > float(row["ask"]):
            errors.append("bid > ask")
    if row.get("timestamp_ms") is not None and int(row["timestamp_ms"]) <= 0:
        errors.append("invalid timestamp_ms")
    return errors


def validate_execution_row(row: dict[str, Any]) -> list[str]:
    errors = []
    missing = EXECUTION_REQUIRED - set(row.keys())
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
    if row.get("timestamp_send_ms") and row.get("timestamp_fill_ms"):
        if int(row["timestamp_fill_ms"]) < int(row["timestamp_send_ms"]):
            errors.append("fill before send")
    return errors


def validate_ticks_batch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = []
    for i, row in enumerate(rows):
        row_errs = validate_tick_row(row)
        for e in row_errs:
            errors.append(f"row {i}: {e}")
    return {"valid": len(errors) == 0, "errors": errors, "count": len(rows)}
