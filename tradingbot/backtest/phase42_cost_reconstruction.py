"""Phase 42 — labeled cost reconstruction on frozen Phase 40 outputs.

RESEARCH ONLY. Never regenerates signals, never changes strategy, never
applies an invented commission, never overwrites Phase 40 artifacts.
Does not import live.py or Phase 40 collector modules.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

UNKNOWN = "UNKNOWN"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE40_SETUPS_JSONL = "logs/phase40_raw_setups.jsonl"
PHASE42_RECON_JSON = "logs/phase42_cost_reconstruction.json"


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def overnight_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = 0
    ge_8h = 0
    ge_9h = 0
    wed_hold = 0
    sl_points: list[float] = []
    for row in rows:
        if row.get("outcome") in (None, "open"):
            continue
        n += 1
        dur = row.get("duration_minutes")
        if isinstance(dur, (int, float)):
            if float(dur) >= 480:
                ge_8h += 1
            if float(dur) >= 540:
                ge_9h += 1
        entry = _parse_ts(row.get("timestamp"))
        exit_t = _parse_ts(row.get("exit_time"))
        if entry is not None and exit_t is not None:
            days = {entry.date(), exit_t.date()}
            if any(d.weekday() == 2 for d in days):
                wed_hold += 1
        try:
            entry_px = float(row.get("entry_price"))
            sl = float(row.get("stop_loss"))
            sl_points.append(abs(entry_px - sl))
        except (TypeError, ValueError):
            pass
    sl_points.sort()
    mid = sl_points[len(sl_points) // 2] if sl_points else None
    return {
        "resolved_trades": n,
        "share_ge_8h": (ge_8h / n) if n else UNKNOWN,
        "share_ge_9h_possible_rollover": (ge_9h / n) if n else UNKNOWN,
        "wednesday_touch_share": (wed_hold / n) if n else UNKNOWN,
        "median_sl_price_units": mid,
        "label": "DERIVED",
        "source": PHASE40_SETUPS_JSONL,
    }


def modeled_swap_drag_R(
    *,
    swap_long: float,
    swap_short: float,
    median_sl: float | None,
    tick_size: float,
    tick_value: float,
    share_overnight: float | None,
) -> dict[str, Any]:
    if not median_sl or median_sl <= 0 or tick_size <= 0:
        return {"status": UNKNOWN, "reason": "SL or tick size missing"}
    ticks = median_sl / tick_size
    risk_usd_per_lot = ticks * tick_value
    if risk_usd_per_lot <= 0:
        return {"status": UNKNOWN, "reason": "risk_usd_per_lot non-positive"}
    long_r = swap_long / risk_usd_per_lot
    short_r = swap_short / risk_usd_per_lot
    return {
        "status": "MODELED",
        "label": "MODELED / SCENARIO — not broker-observed historical swap",
        "assumptions": {
            "one_overnight_on_1_lot": True,
            "risk_from_median_SL": median_sl,
            "tick_size": tick_size,
            "tick_value": tick_value,
            "share_overnight_applied": share_overnight,
        },
        "swap_long_R_per_overnight": long_r,
        "swap_short_R_per_overnight": short_r,
        "expected_drag_if_share_overnight_long_R": (
            None if share_overnight is None else long_r * share_overnight
        ),
        "expected_drag_if_share_overnight_short_R": (
            None if share_overnight is None else short_r * share_overnight
        ),
        "triple_wednesday_note": "Wednesday rollover3days=3 would triple that night. Not applied as observed.",
    }


def reconstruct_frozen_phase40(root: Path, economics: dict[str, Any], swap_rates: dict[str, Any]) -> dict[str, Any]:
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    jsonl = root / PHASE40_SETUPS_JSONL
    rows: list[dict[str, Any]] = []
    if jsonl.is_file():
        with jsonl.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    holds = overnight_candidates(rows)
    share = holds.get("share_ge_9h_possible_rollover")
    share_f = float(share) if isinstance(share, (int, float)) else None
    drag = modeled_swap_drag_R(
        swap_long=float(swap_rates.get("current_swap_long") or 0),
        swap_short=float(swap_rates.get("current_swap_short") or 0),
        median_sl=holds.get("median_sl_price_units") if isinstance(holds.get("median_sl_price_units"), (int, float)) else None,
        tick_size=float(economics.get("tick_size") or 0.01),
        tick_value=float(economics.get("tick_value") or 1.0),
        share_overnight=share_f,
    )
    return {
        "status": "BLOCKED_FOR_EXECUTABLE",
        "commission_applied": False,
        "commission_status": UNKNOWN,
        "signals_regenerated": False,
        "phase40_fingerprint": p40.get("tape_fingerprint"),
        "raw_expectancy_R": (p40.get("raw_performance") or {}).get("expectancy_R"),
        "hold_diagnostics": holds,
        "swap_sensitivity": drag,
        "spread_slip_sensitivity": (p40.get("cost_sensitivity") or {}).get("scenarios"),
        "note": (
            "Frozen Phase 40 outputs only. Commission remains UNKNOWN and is not invented. "
            "This is not an executable backtest and not observed broker PnL."
        ),
    }
