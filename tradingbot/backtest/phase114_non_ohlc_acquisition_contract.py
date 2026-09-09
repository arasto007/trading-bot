"""Phase 114 — full-horizon non-OHLC data acquisition contract.

RESEARCH / DATA-CONTRACT ONLY. Does not acquire data, connect to MT5,
read .env, or modify production. Does not start Phase 115.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    _git_head,
    _parse_ts,
    _utc_now,
)
from tradingbot.backtest.phase68_exit_forensics import BAR_MINUTES, TAPE_END_FALLBACK
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase82_profit_protection_design import REVERSAL_BARS, STRUCTURAL_FRACTION
from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON, STATE_LEVELS
from tradingbot.backtest.phase106_non_ohlc_data_inventory import PHASE106_JSON
from tradingbot.backtest.phase113_non_ohlc_final_gate import PHASE113_JSON

PHASE = "114"
PHASE114_JSON = "logs/phase114_non_ohlc_acquisition_contract.json"
PHASE114_MD = "docs/PHASE114_NON_OHLC_ACQUISITION_CONTRACT.md"
BLOCKED = "BLOCKED"
CANONICAL_SYMBOL = "XAUUSD_i"
LOGICAL_SYMBOL = "XAUUSD"
TZ = "UTC"
# Predeclared from news_logic defaults. Causal research uses BEFORE-entry only.
NEWS_MINUTES_BEFORE = 30
# Closed-bar pad = one bar of that timeframe. Not searched.
H4_MINUTES = 240
H1_MINUTES = 60
M15_MINUTES = 15
M1_MINUTES = 1
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "ACQUISITION_READY",
    "horizon",
    "final_gate",
    "production_safety",
    "artifacts",
)


def measure_horizon(events: list[dict[str, Any]], tape_end: datetime | None = None) -> dict[str, Any]:
    rows = []
    for e in events:
        ts = _parse_ts(e.get("timestamp"))
        hold = _f(e.get("duration_minutes"))
        if ts is None:
            continue
        exit_ts = ts + timedelta(minutes=hold) if hold is not None else None
        rows.append((ts, exit_ts, hold))
    if not rows:
        return {"n": 0}
    first = min(r[0] for r in rows)
    last_entry = max(r[0] for r in rows)
    exits = [r[1] for r in rows if r[1] is not None]
    last_exit = max(exits) if exits else last_entry
    holds = [r[2] for r in rows if r[2] is not None]
    h4_lookback = timedelta(minutes=(REVERSAL_BARS + 1) * H4_MINUTES)
    m5_pad = timedelta(minutes=BAR_MINUTES)
    acq_start = first - h4_lookback
    tape_end = tape_end or TAPE_END_FALLBACK
    acq_end = max(last_exit, tape_end)
    return {
        "n_events": len(rows),
        "earliest_event_timestamp": first.isoformat(),
        "latest_event_timestamp": last_entry.isoformat(),
        "latest_event_exit_timestamp": last_exit.isoformat(),
        "max_hold_minutes": max(holds) if holds else None,
        "median_hold_minutes": sorted(holds)[len(holds) // 2] if holds else None,
        "timezone": TZ,
        "symbol": CANONICAL_SYMBOL,
        "timestamp_precision": {
            "events": "second",
            "ticks_required": "millisecond",
            "bars_required": "second (bar open, MT5 copy_rates convention)",
        },
        "coverage_before_entry": {
            "tick_spread_m1": f"{BAR_MINUTES} minutes (one M5 bar open before signal timestamp)",
            "m15": f"{(REVERSAL_BARS + 1) * M15_MINUTES} minutes (REVERSAL_BARS+1 closed M15)",
            "h1": f"{(REVERSAL_BARS + 1) * H1_MINUTES} minutes",
            "h4": f"{(REVERSAL_BARS + 1) * H4_MINUTES} minutes",
            "news": f"{NEWS_MINUTES_BEFORE} minutes (news_logic minutes_before; scheduled time only)",
            "source": "CODE-EVIDENCE REVERSAL_BARS / BAR_MINUTES / news_logic; not searched",
        },
        "coverage_after_entry": "through each event's measured exit (duration_minutes); do not cap the +31.84R path",
        "coverage_full_lifecycle": "signal M5-bar open → exit bar inclusive",
        "acquisition_start_utc": acq_start.isoformat(),
        "acquisition_end_utc": acq_end.isoformat(),
        "m5_pad_minutes": BAR_MINUTES,
        "h4_lookback_minutes": (REVERSAL_BARS + 1) * H4_MINUTES,
        "frozen_tape_end": tape_end.isoformat(),
        "future_leakage": "joins must use only observations with timestamp < event state time (ticks) or fully closed bars (OHLC)",
        "population": "Phase40 resolved events, n=419; 2847 jsonl rows are not independent",
        "do_not_alter_frozen_tape": True,
    }


def tick_contract(horizon: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": CANONICAL_SYMBOL,
        "logical_xauusd_forbidden": True,
        "date_range": [horizon.get("acquisition_start_utc"), horizon.get("acquisition_end_utc")],
        "required_fields": [
            {"name": "timestamp_utc", "role": "REQUIRED", "precision": "millisecond"},
            {"name": "bid", "role": "REQUIRED"},
            {"name": "ask", "role": "REQUIRED"},
        ],
        "optional_fields": [
            {"name": "last", "role": "OPTIONAL"},
            {"name": "volume", "role": "OPTIONAL"},
            {"name": "flags", "role": "OPTIONAL"},
            {"name": "source", "role": "OPTIONAL"},
            {"name": "time_msc", "role": "OPTIONAL", "note": "MT5 millisecond epoch if present"},
        ],
        "ordering": "non-decreasing timestamp_utc",
        "duplicate_policy": "drop exact duplicate (timestamp_utc, bid, ask); keep first",
        "missing_interval_policy": "weekend/holiday gaps allowed; a gap inside an event lifecycle weekday window marks that event PARTIAL, do not impute",
        "timezone": TZ,
        "bid_ask_validity": "bid > 0 and ask > 0 and ask >= bid",
        "impossible_price_policy": "quarantine row; do not interpolate",
        "zero_negative_spread_policy": "ask < bid INVALID; ask == bid quarantined (do not impute)",
        "out_of_order_policy": "sort by timestamp_utc; if >1% rows moved, dataset INVALID",
        "classes": {
            "TICK_DATA_COMPLETE": "schema valid AND symbol XAUUSD_i AND all 419 events have ticks from M5-bar-open through exit",
            "TICK_DATA_PARTIAL": "schema valid but event coverage < 419",
            "TICK_DATA_INVALID": "wrong symbol, timezone, or validity rules fail at dataset level",
            "TICK_DATA_MISSING": "no usable local file (current state)",
        },
        "vendor_assumed": False,
        "current_local_status": "TICK_DATA_MISSING",
        "evidence_kind": "INFERENCE",
    }


def spread_contract(horizon: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": CANONICAL_SYMBOL,
        "date_range": [horizon.get("acquisition_start_utc"), horizon.get("acquisition_end_utc")],
        "preferred_supply": "BOTH: bid and ask required; spread_price = ask - bid MAY be supplied as derived column",
        "standalone_spread_without_bid_ask": "INSUFFICIENT (cannot validate sign or reconstruct mid)",
        "required_fields": ["timestamp_utc", "bid", "ask"],
        "optional_fields": ["spread_price", "spread_min", "spread_max", "tick_count"],
        "spread_definition": "ask - bid in price units; do not convert to pips without a documented XAUUSD_i tick size from the same source",
        "causal_alignment": "at event state T, use last tick/quote with timestamp_utc <= T; never future quotes",
        "broker_economics": "not inferred; observed quotes only",
        "classes": {
            "SPREAD_DATA_COMPLETE": "bid/ask present for all 419 event lifecycles",
            "SPREAD_DATA_PARTIAL": "subset of events",
            "SPREAD_DATA_INVALID": "wrong symbol or ask < bid as a dataset property",
            "SPREAD_DATA_MISSING": "current local sidecars do not cover the event tape",
        },
        "current_local_status": "SPREAD_DATA_MISSING",
        "note": "If tick contract is COMPLETE, spread is derived; a separate spread file is then redundant.",
        "evidence_kind": "INFERENCE",
    }


def tf_contract(tf: str, minutes: int, horizon: dict[str, Any], local_note: str) -> dict[str, Any]:
    lookback = (REVERSAL_BARS + 1) * minutes
    return {
        "timeframe": tf,
        "symbol": CANONICAL_SYMBOL,
        "date_range": [horizon.get("acquisition_start_utc"), horizon.get("acquisition_end_utc")],
        "required_fields": ["time", "open", "high", "low", "close", "volume"],
        "optional_fields": [],
        "indicators_required": False,
        "indicators_note": "ATR/RSI/etc. only if reconstructed later from these OHLCV bars; not an acquisition field",
        "timezone": TZ,
        "timestamp_semantics": "bar OPEN (MT5 copy_rates convention). Closed iff time + duration <= event_state_ts",
        "duplicate_policy": "one row per bar open; keep last if OHLC conflict then INVALID",
        "gap_policy": "weekend/holiday allowed; missing bars inside an event weekday window = PARTIAL for that event",
        "lookback_before_entry_minutes": lookback,
        "purpose": "causal HTF context research; not strategy redesign",
        "local_note": local_note,
        "logical_xauusd_forbidden": True,
    }


def news_contract(horizon: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol_context": "gold / USD (calendar is not a symbol tape)",
        "date_range": [horizon.get("acquisition_start_utc"), horizon.get("acquisition_end_utc")],
        "fields": {
            "event_timestamp_utc": "REQUIRED",
            "event_name": "REQUIRED",
            "importance": "REQUIRED if the source has it; else OPTIONAL",
            "currency": "OPTIONAL",
            "country": "OPTIONAL",
            "category": "OPTIONAL",
            "forecast": "OPTIONAL; AVAILABLE FACT only if present in the historical record",
            "previous": "OPTIONAL",
            "actual": "OPTIONAL; UNAVAILABLE as a causal predictor at entry if print time >= entry",
            "source_provider": "REQUIRED",
        },
        "do_not_fabricate": True,
        "do_not_use_generator": "tradingbot/ml/data/news_calendar.py is not a historical dataset",
        "causal_window": {
            "minutes_before_entry": NEWS_MINUTES_BEFORE,
            "minutes_after_entry_as_feature": 0,
            "scheduled_time_known_before": "ALLOWED as proximity feature if timestamp < entry",
            "actual_print": "FORBIDDEN as a feature if print_ts >= entry; FORBIDDEN to use the numeric surprise before it exists",
        },
        "current_local_status": "NEWS_DATA_MISSING",
        "evidence_kind": "DATA_MISSING",
    }


def alignment_contract() -> dict[str, Any]:
    levels = list(STATE_LEVELS)
    return {
        "statistical_unit": "EVENT (utc_date, side); 2847 jsonl rows are members",
        "left_key": "phase40/phase98 event timestamp (UTC)",
        "joins": [
            {
                "name": "tick_to_event_lifecycle",
                "left_key": "event.timestamp / anatomy bar timestamps",
                "right_key": "tick.timestamp_utc",
                "join_window": "[M5_bar_open(entry), exit_ts]",
                "causal_cut_off": "tick.timestamp_utc <= state_ts",
                "tolerance": "0 ms after UTC normalize; milliseconds kept",
                "missing_data": "event excluded from tick analysis; do not impute",
            },
            {
                "name": "tick_at_first_favorable_levels",
                "left_key": "phase98 states[level].bar → M5 bar time",
                "right_key": "tick.timestamp_utc",
                "join_window": "M5 bar that first reaches +0.25/+0.5/+1/+1.5/+2R",
                "causal_cut_off": "ticks inside that bar with time <= bar_close; same-bar SL not assumed favorable-first",
                "tolerance": "bar duration 5 minutes",
                "missing_data": "level snapshot remains M5-only",
                "levels": levels,
            },
            {
                "name": "tick_at_retracement",
                "left_key": "phase98 anatomy.retrace.bar",
                "right_key": "tick.timestamp_utc",
                "join_window": "retracement M5 bar",
                "causal_cut_off": "tick.timestamp_utc <= retrace_bar_close",
                "tolerance": "5 minutes",
                "missing_data": "skip tick features for that event",
            },
            {
                "name": "m15_h1_h4_asof",
                "left_key": "event.timestamp",
                "right_key": "bar.time (open)",
                "join_window": "last bar with time + tf_minutes <= event.timestamp (closed)",
                "causal_cut_off": "closed bar only; never the forming bar",
                "tolerance": "0 after UTC normalize",
                "missing_data": "event uncovered; DATA_LIMITED",
            },
            {
                "name": "news_proximity",
                "left_key": "event.timestamp",
                "right_key": "news.event_timestamp_utc",
                "join_window": f"[{NEWS_MINUTES_BEFORE} minutes before entry, entry)",
                "causal_cut_off": "news.event_timestamp_utc < entry",
                "tolerance": "1 second after UTC normalize",
                "missing_data": "treat as no-news; do not fabricate",
            },
        ],
        "research_not_executed_in_phase114": True,
        "evidence_kind": "INFERENCE",
    }


def quality_gate() -> dict[str, Any]:
    return {
        "thresholds_searched": False,
        "event_coverage_complete": 419,
        "event_coverage_note": "COMPLETE = 419/419 events; not the Phase106 0.5 inventory bar",
        "checklist": [
            {"id": 1, "name": "coverage", "pass": "rows span acquisition_start to acquisition_end for the dataset's timeframe"},
            {"id": 2, "name": "timestamp_integrity", "pass": "parseable UTC; no NaT"},
            {"id": 3, "name": "symbol_integrity", "pass": "literal XAUUSD_i; reject XAUUSD"},
            {"id": 4, "name": "chronology", "pass": "non-decreasing time"},
            {"id": 5, "name": "duplicates", "pass": "policy applied; residual exact dupes = 0"},
            {"id": 6, "name": "gaps", "pass": "no unflagged weekday gap inside any event lifecycle"},
            {"id": 7, "name": "invalid_values", "pass": "OHLC high>=low; tick ask>=bid>0; volume>=0"},
            {"id": 8, "name": "timezone_consistency", "pass": "UTC only"},
            {"id": 9, "name": "causal_usability", "pass": "closed-bar / as-of rules implementable without future rows"},
            {"id": 10, "name": "event_coverage", "pass": "419/419 for COMPLETE"},
            {"id": 11, "name": "cross_source_consistency", "pass": "M15/H1/H4 aggregates must not contradict M5 OHLC on overlapping closed bars beyond quarantine"},
        ],
        "evidence_kind": "INFERENCE",
    }


def source_options() -> dict[str, Any]:
    return {
        "categories": [
            "existing repository files (Phase106 inventory; incomplete)",
            "broker-exported historical data labeled XAUUSD_i",
            "authorized historical market-data provider",
            "public historical datasets",
        ],
        "downloaded": False,
        "accounts_connected": False,
        "specific_paid_provider_recommended": False,
        "symbol_distinction": {
            "canonical": CANONICAL_SYMBOL,
            "not_a_substitute": LOGICAL_SYMBOL,
            "EV-EQ-01": "NOT_PROVEN",
            "silent_substitution": "FORBIDDEN",
        },
        "note": "No vendor is assumed to contain XAUUSD_i. Operator must prove symbol identity before ingest.",
        "evidence_kind": "INFERENCE",
    }


def priority(p106: dict[str, Any], p113: dict[str, Any]) -> dict[str, Any]:
    """Evidence-based rank. Not the prompt's example order."""
    ranked = [
        {
            "rank": 1,
            "dataset": "TICK_BID_ASK",
            "why": "Phase98 n_ambiguous=394 same-bar fav+adv; only ticks can order favorable vs adverse inside the M5 bar. Highest chance to separate C/D vs E/F.",
            "coverage_now": "tick overlap 0–3/419 (Phase106/107)",
            "causal_fidelity": "highest",
            "availability": "MISSING at horizon",
            "complexity": "high volume",
        },
        {
            "rank": 2,
            "dataset": "M1_XAUUSD_I",
            "why": "Fallback if ticks cannot be obtained; still finer than M5 for path ordering. Current overlap 8/419.",
            "coverage_now": "AVAILABLE_BUT_INCOMPLETE",
            "causal_fidelity": "high",
            "availability": "partial 32-day sidecar",
            "complexity": "medium",
        },
        {
            "rank": 3,
            "dataset": "SPREAD_FROM_BID_ASK",
            "why": "Redundant if rank-1 ticks include bid/ask. Standalone spread without bid/ask cannot validate. Not a separate first acquire.",
            "coverage_now": "SPREAD_DATA_MISSING for events",
            "causal_fidelity": "medium (cost/state, weaker C/D vs E/F theory than path ordering)",
            "availability": "sidecar days only",
            "complexity": "low if derived from ticks",
        },
        {
            "rank": 4,
            "dataset": "H1_XAUUSD_I",
            "why": "Never existed canonically. Architecture names H4 bias / M15 context; H1 is the missing middle. Lower than path data because M15 already showed overlap.",
            "coverage_now": "MISSING canonical",
            "causal_fidelity": "medium",
            "availability": "none for XAUUSD_i",
            "complexity": "low",
        },
        {
            "rank": 5,
            "dataset": "M15_GAP_FILL",
            "why": "229/419 already joined; Phase109 HTF_DISCRIMINATOR=UNSUPPORTED. Filling 2023-02→2024-07 is completeness, not a new mechanism.",
            "coverage_now": "AVAILABLE_AND_USABLE incomplete",
            "causal_fidelity": "already tested, negative",
            "availability": "partial",
            "complexity": "low",
        },
        {
            "rank": 6,
            "dataset": "H4_FULL_HORIZON",
            "why": "Short XAUUSD_i H4 only. Same HTF family as M15 which did not separate C/D vs E/F.",
            "coverage_now": "AVAILABLE_BUT_INCOMPLETE",
            "causal_fidelity": "low given Phase109",
            "availability": "partial",
            "complexity": "low",
        },
        {
            "rank": 7,
            "dataset": "NEWS_CALENDAR",
            "why": "Entirely missing, but weaker causal story for giveback vs tail and must not use future actuals. Acquire after path data.",
            "coverage_now": "MISSING",
            "causal_fidelity": "low–medium",
            "availability": "none",
            "complexity": "provider-dependent",
        },
    ]
    return {
        "prompt_example_order_not_used": True,
        "ranked": ranked,
        "DATA_PRIORITY": [r["dataset"] for r in ranked],
        "phase113_next": (p113 or {}).get("NEXT_RESEARCH_TARGET"),
        "evidence_kind": "INFERENCE",
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phase 114 (`docs/PHASE114_NON_OHLC_ACQUISITION_CONTRACT.md`) is a research-only "
        "acquisition contract. It does not download data, connect to MT5, read .env, "
        "modify production, or implement an exit spec."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 106–113"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase114_non_ohlc_acquisition_contract.py` — **RESEARCH_ONLY** "
        "acquisition contract; data not acquired.\n"
    )
    needle = "`tradingbot/backtest/phase113_non_ohlc_final_gate.py`"
    if "phase114_non_ohlc_acquisition_contract.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 114 started | **NO** |", "| Phase 114 started | **YES** |")
    block = f"""

## Non-OHLC acquisition contract (Phase 114)

| Claim | Status |
|---|---|
| ACQUISITION_READY | **{payload.get("ACQUISITION_READY")}** |
| DATA_ACQUIRED | **NO** |
| CONTRACT_COMPLETE | **{payload.get("CONTRACT_COMPLETE")}** |
| NEXT_RESEARCH_TARGET | **{payload.get("NEXT_RESEARCH_TARGET")}** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| Intervention implemented | **NO** |
| MT5 used | **NO** |
| ENV read | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 115 started | **NO** |
"""
    marker = "## Non-OHLC acquisition contract (Phase 114)"
    if marker in ktext:
        start = ktext.find(marker)
        ku.write_text(ktext[:start].rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")


def append_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = root / LEDGER_MD
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    extra = [
        "",
        "## Phase 114",
        "",
        "| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| H114-01 | {today} | 114 | frozen Phase38/40 | 419 | event tape 419 resolved | {payload.get('ACQUISITION_READY')} | reported | NO | contract; not acquired |",
        "",
        f"**ACQUISITION_READY:** `{payload.get('ACQUISITION_READY')}`",
        f"**NEXT_RESEARCH_TARGET:** `{payload.get('NEXT_RESEARCH_TARGET')}` (not started).",
        "",
    ]
    marker = "## Phase 114"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def run_phase114_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    p106 = _safe_load_json(root / PHASE106_JSON) or {}
    p113 = _safe_load_json(root / PHASE113_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    horizon = measure_horizon(events, tape_end)
    tick = tick_contract(horizon)
    spread = spread_contract(horizon)
    m1 = tf_contract("M1", M1_MINUTES, horizon, "local 32-day sidecar only")
    m15 = tf_contract("M15", M15_MINUTES, horizon, "phase38 parquet usable from 2024-07-25; gap before that")
    h1 = tf_contract("H1", H1_MINUTES, horizon, "no canonical XAUUSD_i file")
    h4 = tf_contract("H4", H4_MINUTES, horizon, "short XAUUSD_i snapshot only")
    news = news_contract(horizon)
    align = alignment_contract()
    quality = quality_gate()
    sources = source_options()
    prio = priority(p106, p113)
    # Contract is complete. Execution of acquire is forbidden here.
    # Ready means Phase115 may start acquisition IF an operator-authorized XAUUSD_i source exists.
    # No vendor is selected. Silent XAUUSD substitution remains forbidden.
    ready = True
    nxt = "OPERATOR_AUTHORIZED_XAUUSD_I_INGEST"
    blocker = None
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "data_acquired": False,
        "intervention_implemented": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "n_events": horizon.get("n_events"),
        "n_raw_signals_not_independent": 2847,
        "outlier_kept": True,
        "outlier_ts": next((r.get("ts") for r in (p98.get("compact") or []) if r.get("path_class") == "F"), None),
        "horizon": horizon,
        "tick_contract": tick,
        "spread_contract": spread,
        "m1_contract": m1,
        "m15_contract": m15,
        "h1_contract": h1,
        "h4_contract": h4,
        "news_contract": news,
        "alignment_contract": align,
        "quality_gate": quality,
        "source_options": sources,
        "priority": prio,
        "REQUIRED_TICK_DATA": tick["current_local_status"],
        "REQUIRED_SPREAD_DATA": spread["current_local_status"],
        "REQUIRED_M1_DATA": "PARTIAL_LOCAL",
        "REQUIRED_H1_DATA": "MISSING_CANONICAL",
        "REQUIRED_M15_DATA": "PARTIAL_LOCAL",
        "REQUIRED_H4_DATA": "PARTIAL_LOCAL",
        "REQUIRED_NEWS_DATA": news["current_local_status"],
        "DATA_PRIORITY": prio["DATA_PRIORITY"],
        "CONTRACT_COMPLETE": True,
        "ACQUISITION_READY": ready,
        "DATA_ACQUIRED": False,
        "blocker": blocker,
        "phase115_may_begin_if": "Operator authorizes ingest of proven XAUUSD_i files; no MT5/.env in 114; no silent XAUUSD map",
        "NEXT_RESEARCH_TARGET": nxt,
        "PRIMARY_EXIT_MECHANISM": p113.get("PRIMARY_EXIT_MECHANISM") or "PROFIT_GIVEBACK",
        "SECONDARY_EXIT_MECHANISM": p113.get("SECONDARY_EXIT_MECHANISM") or "EXIT_GEOMETRY",
        "DISCRIMINATOR_STATUS": p113.get("DISCRIMINATOR_STATUS") or "UNSUPPORTED",
        "EXIT_DESIGN_SPEC_STATUS": "INSUFFICIENT_EVIDENCE",
        "FINAL_GATE": "GO_RESEARCH",
        "FINAL_RESEARCH_GATE": "GO_RESEARCH",
        "PARAMETER_SEARCH_USED": False,
        "OPTIMIZATION_USED": False,
        "PRODUCTION_CHANGED": False,
        "MT5_USED": False,
        "LIVE_TRADING": False,
        "ORDERS_PLACED": False,
        "ENV_ACCESSED": False,
        "RISK_GATE_CHANGED": False,
        "TRADING_KERNEL_CHANGED": False,
        "EXECUTION_CHANGED": False,
        "STRATEGY_CHANGED": False,
        "CALIBRATION_CHANGED": False,
        "SIZING_CHANGED": False,
        "SLTP_CHANGED": False,
        "ML_ACTIVATED": False,
        "EXIT_DESIGN_SPEC_IMPLEMENTED": False,
        "evidence_kind": "INFERENCE",
        "hypotheses": [
            {
                "id": "H114-01",
                "claim": "A complete non-OHLC acquisition contract can be specified from the frozen 419-event tape without acquiring data.",
                "result": "SUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["horizon_from_phase74_events"],
        "oos_used_for_selection": False,
        "final_gate": "GO_RESEARCH",
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "MT5": "NOT_USED",
            "DATA_ACQUIRED": False,
            "production_changes": "NONE",
            "spec_implemented": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE114_JSON, "md": PHASE114_MD, "ledger": LEDGER_MD},
    }
    (root / PHASE114_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE114_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    h = horizon
    lines = [
        "# Phase 114 — Non-OHLC Acquisition Contract",
        "",
        "INFERENCE over FROZEN-DATA-EVIDENCE (event timestamps) and CODE-EVIDENCE (lookback constants). Data not acquired.",
        f"**ACQUISITION_READY:** `{ready}`",
        f"**DATA_ACQUIRED:** `false`",
        f"**CONTRACT_COMPLETE:** `true`",
        "",
        "## 114A Horizon",
        f"- earliest event: `{h.get('earliest_event_timestamp')}`",
        f"- latest event: `{h.get('latest_event_timestamp')}`",
        f"- latest exit: `{h.get('latest_event_exit_timestamp')}`",
        f"- acquisition window: `{h.get('acquisition_start_utc')}` → `{h.get('acquisition_end_utc')}`",
        f"- symbol: `{CANONICAL_SYMBOL}` (not `{LOGICAL_SYMBOL}`)",
        f"- timezone: `{TZ}`",
        f"- tick precision: millisecond; bars: bar-open seconds",
        f"- before entry: H4 lookback {(REVERSAL_BARS + 1) * H4_MINUTES} min; news {NEWS_MINUTES_BEFORE} min scheduled-only",
        f"- after entry: through measured exit; max hold `{h.get('max_hold_minutes')}` minutes; do not cap +31.84R",
        "",
        "## 114B Tick schema",
        "REQUIRED: `timestamp_utc`, `bid`, `ask`. OPTIONAL: last, volume, flags, source.",
        "COMPLETE = 419/419 event lifecycles. Current local status: `TICK_DATA_MISSING`.",
        "",
        "## 114C Spread",
        "Prefer bid+ask; derive spread. Do not infer broker economics. Current: `SPREAD_DATA_MISSING`.",
        "",
        "## 114D Timeframes",
        "M1 / M15 / H1 / H4 OHLCV, `XAUUSD_i`, UTC, bar-open closed-bar semantics. No indicators as acquisition fields.",
        "",
        "## 114E News",
        f"REQUIRED: event_timestamp_utc, event_name, source_provider. Actual values are not causal predictors at/after entry. Window: {NEWS_MINUTES_BEFORE} min before entry. Do not use the in-repo generator.",
        "",
        "## 114F Alignment",
        "Event unit. As-of ticks `timestamp <= state_ts`. HTF last closed bar. News scheduled time `< entry`. Research not run in this phase.",
        "",
        "## 114G Quality gate",
        "11-point checklist. COMPLETE requires 419/419 coverage. Thresholds not searched.",
        "",
        "## 114H Sources",
        "Repo files / broker export / authorized provider / public datasets. No download. No XAUUSD substitute.",
        "",
        "## 114I Priority",
        "1. Tick+bid/ask  2. M1  3. Spread-from-quotes  4. H1  5. M15 gap  6. H4  7. News",
        "Rationale: same-bar path ordering is the unresolved C/D vs E/F question; M15 already failed as a discriminator.",
        "",
        "## 114J Stop",
        "Data not acquired. Phase 115 not started. Operator must authorize a proven `XAUUSD_i` source before ingest.",
        f"**NEXT_RESEARCH_TARGET:** `{nxt}`",
        "",
    ]
    (root / PHASE114_MD).write_text("\n".join(lines), encoding="utf-8")
    append_ledger(root, payload)
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    p = run_phase114_collection(Path("."))
    print(p["ACQUISITION_READY"], p["DATA_PRIORITY"])
