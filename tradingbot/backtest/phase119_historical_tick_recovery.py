"""Phase 119 - historical XAUUSD_i tick recovery and source resolution.

RESEARCH / SOURCE-RESOLUTION ONLY.
Determines whether a verified full-horizon LiteFinance XAUUSD_i tick source
exists for the missing window before the Phase 118 export.

Does not connect to MT5, read .env, download remote data, modify production,
design exits, optimize, alter the Phase 118 raw export, or start Phase 120.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    _git_head,
    _utc_now,
)
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase114_non_ohlc_acquisition_contract import CANONICAL_SYMBOL, TZ
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    EXPECTED_JSONL_SHA256,
    N_AMBIGUOUS_394,
    N_EVENTS,
    PHASE40_TS,
    file_sha256,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import OUTLIER_TS, substitution_verdict
from tradingbot.backtest.phase117_operator_source_resolution import RAW_DROP_REL
from tradingbot.backtest.phase118_tick_forensic_validation import (
    EXPECTED_RAW_SHA256,
    PHASE118_JSON,
)

PHASE = "119"
PHASE119_JSON = "logs/phase119_historical_tick_recovery.json"
PHASE119_MD = "docs/PHASE119_HISTORICAL_TICK_RECOVERY.md"
PHASE116_JSON = "logs/phase116_data_source_research.json"
PHASE117_JSON = "logs/phase117_operator_source_resolution.json"
MISSING_START = ACQ_START_ISO  # 2023-02-26T15:40:00Z
MISSING_END = "2026-07-23T01:00:59Z"
PHASE118_FIRST = "2026-07-23T01:01:00.042000Z"
PHASE118_LAST = "2026-09-07T20:09:56.006000Z"
RESEARCH_DATE = datetime.now(timezone.utc).date().isoformat()

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PHASE119_STATUS",
    "SOURCE_RESEARCH_STATUS",
    "CANONICAL_SOURCE_AVAILABLE",
    "ACQUISITION_STATUS",
    "OPERATOR_ACTION_REQUIRED",
    "DATA_ACQUIRED",
    "final_gate",
    "production_safety",
    "artifacts",
)

LOCAL_TICK_CANDIDATES = (
    "data/research/non_ohlc/raw/phase117_operator_export/XAUUSD_i_202607230101_202609072009.csv",
    "data/XAUUSD_i_ticks_phase38.parquet",
    "logs/phase27_26_xauusd_i_ticks.parquet",
    "logs/phase27_25_xauusd_i_ticks.parquet",
    "logs/phase27_23_xauusd_i_ticks.parquet",
)

def _iso(ts: Any) -> str | None:
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.isoformat().replace("+00:00", "Z")


def _covers(start: str | None, end: str | None, point: str) -> bool | None:
    if not start or not end:
        return None
    return bool(pd.Timestamp(start) <= pd.Timestamp(point) <= pd.Timestamp(end))


def _full_missing_covered(start: str | None, end: str | None) -> bool:
    if not start or not end:
        return False
    return bool(pd.Timestamp(start) <= pd.Timestamp(MISSING_START) and pd.Timestamp(end) >= pd.Timestamp(MISSING_END))


def prior_phase_evidence(root: Path) -> dict[str, Any]:
    p116 = _safe_load_json(root / PHASE116_JSON) or {}
    p117 = _safe_load_json(root / PHASE117_JSON) or {}
    p118 = _safe_load_json(root / PHASE118_JSON) or {}
    known = [
        "LiteFinance CLASSIC XAUUSD_i is the canonical gold symbol (operator-verified).",
        "Phase116: exact broker tick methods exist (Symbols Ticks tab, copy_ticks_range, TKC) but full-horizon retention is unpublished.",
        "Phase116: Dukascopy/HistData/COMEX/generic XAUUSD are REJECTED as canonical; EV-EQ-01 NOT_PROVEN.",
        "Phase117: operator export procedure defined; drop zone ready.",
        "Phase118: operator supplied verified XAUUSD_i export covering only 2026-07-23..2026-09-07 (~10.1M rows).",
        "Phase118: 12/419 events covered; 12 of 394 ambiguities resolved; +31.84R uncovered.",
        "Phase118 raw SHA256 preserved: " + EXPECTED_RAW_SHA256,
    ]
    unknown = [
        "LiteFinance history-server tick retention depth for XAUUSD_i before 2026-07-23",
        "Whether Symbols->Ticks Request can retrieve 2023-02-26..2026-07-22 from the server",
        "Whether LiteFinance support can provide a historical XAUUSD_i tick dump",
        "Whether any third-party feed is exactly equivalent to LiteFinance XAUUSD_i (EV-EQ-01)",
    ]
    return {
        "phase116": {
            "STATUS": p116.get("PHASE116_STATUS"),
            "ACQUISITION_PATH_STATUS": p116.get("ACQUISITION_PATH_STATUS"),
            "PRIMARY_SOURCE": p116.get("PRIMARY_SOURCE"),
            "SECONDARY_SOURCE": p116.get("SECONDARY_SOURCE"),
            "FALLBACK_SOURCE": p116.get("FALLBACK_SOURCE"),
            "FULL_HORIZON_SOURCES": p116.get("FULL_HORIZON_SOURCES"),
            "GENERIC_XAUUSD_STATUS": p116.get("GENERIC_XAUUSD_STATUS"),
            "BLOCKER": p116.get("BLOCKER"),
        },
        "phase117": {
            "STATUS": p117.get("PHASE117_STATUS"),
            "ACQUISITION_STATUS": p117.get("ACQUISITION_STATUS"),
            "DATA_ACQUIRED": p117.get("DATA_ACQUIRED"),
        },
        "phase118": {
            "STATUS": p118.get("PHASE118_STATUS"),
            "RAW_FILE_SHA256": p118.get("RAW_FILE_SHA256"),
            "ACTUAL_FIRST_TICK": p118.get("ACTUAL_FIRST_TICK"),
            "ACTUAL_LAST_TICK": p118.get("ACTUAL_LAST_TICK"),
            "TICK_EVENT_COVERAGE": p118.get("TICK_EVENT_COVERAGE"),
            "AMBIGUOUS_394_RESOLVED": p118.get("AMBIGUOUS_394_RESOLVED"),
            "AMBIGUOUS_394_REMAINING": p118.get("AMBIGUOUS_394_REMAINING"),
            "OUTLIER_31_84R_COVERAGE": p118.get("OUTLIER_31_84R_COVERAGE"),
            "HISTORY_RANGE_STATUS": p118.get("HISTORY_RANGE_STATUS"),
        },
        "known": known,
        "unknown": unknown,
    }


def inspect_local_tick_file(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    row: dict[str, Any] = {
        "path": rel.replace("\\", "/"),
        "exists": path.is_file(),
        "symbol_identity_ok": verify_xauusd_i(path=rel),
        "canonical_status": "REJECTED",
    }
    if not path.is_file():
        row["canonical_status"] = "MISSING"
        return row
    row["size_bytes"] = int(path.stat().st_size)
    row["sha256"] = file_sha256(path)
    first = last = None
    n_rows = None
    bid = ask = False
    try:
        if path.suffix.lower() == ".csv":
            # Do not fully load 454MB; use Phase118 facts for the known export.
            if EXPECTED_RAW_SHA256 and row["sha256"] == EXPECTED_RAW_SHA256:
                first, last, n_rows = PHASE118_FIRST, PHASE118_LAST, 10124838
                bid = ask = True
            else:
                head = pd.read_csv(path, sep="\t", nrows=5)
                bid = any("bid" in c.lower() for c in head.columns)
                ask = any("ask" in c.lower() for c in head.columns)
        else:
            df = pd.read_parquet(path)
            n_rows = int(len(df))
            bid = "bid" in df.columns
            ask = "ask" in df.columns
            if "time_utc" in df.columns:
                t = pd.to_datetime(df["time_utc"], utc=True)
            elif "time_msc" in df.columns:
                t = pd.to_datetime(pd.to_numeric(df["time_msc"], errors="coerce"), unit="ms", utc=True)
            elif "timestamp_utc" in df.columns:
                t = pd.to_datetime(df["timestamp_utc"], utc=True)
            else:
                t = pd.to_datetime(df.get("time"), utc=True)
            first, last = _iso(t.min()), _iso(t.max())
    except Exception as exc:  # noqa: BLE001 - research catalog must not crash
        row["error"] = str(exc)
    row.update(
        {
            "n_rows": n_rows,
            "first_tick": first,
            "last_tick": last,
            "bid_available": bid,
            "ask_available": ask,
            "covers_missing_window": _full_missing_covered(first, last),
            "covers_outlier": _covers(first, last, OUTLIER_TS),
            "covers_acq_window": _full_missing_covered(first, last)
            and bool(last and pd.Timestamp(last) >= pd.Timestamp(ACQ_END_ISO)),
        }
    )
    if row["symbol_identity_ok"] and bid and ask:
        if row["covers_missing_window"]:
            row["canonical_status"] = "VERIFIED"
        else:
            row["canonical_status"] = "PARTIAL"
    elif not row["symbol_identity_ok"]:
        row["canonical_status"] = "REJECTED"
    else:
        row["canonical_status"] = "NOT_PROVEN"
    return row


def local_source_inventory(root: Path) -> list[dict[str, Any]]:
    return [inspect_local_tick_file(root, rel) for rel in LOCAL_TICK_CANDIDATES]


def source_catalog() -> list[dict[str, Any]]:
    """Public-doc / prior-phase catalog. No remote acquisition performed."""
    rows = [
        {
            "SOURCE_NAME": "LITEFINANCE_MT5_SYMBOLS_TICKS_TAB_EXPORT",
            "SOURCE_TYPE": "broker_terminal_history_export",
            "SYMBOL_AVAILABLE": CANONICAL_SYMBOL,
            "EXACT_XAUUSD_I_IDENTITY": "VERIFIED",
            "BID_AVAILABLE": "VERIFIED",
            "ASK_AVAILABLE": "VERIFIED",
            "TIMESTAMP_PRECISION": "millisecond",
            "HISTORICAL_RANGE": "UNKNOWN (server retention unpublished; Phase118 measured only 2026-07-23..2026-09-07)",
            "2026_01_21_COVERAGE": "UNKNOWN",
            "FULL_REQUIRED_RANGE": "UNKNOWN",
            "LITEFINANCE_FEED_EQUIVALENCE": "VERIFIED",
            "ACCESS_METHOD": "Operator MT5 Symbols->XAUUSD_i->Ticks->Request->Export",
            "CREDENTIAL_REQUIRED": True,
            "PAYMENT_REQUIRED": False,
            "OPERATOR_ACTION_REQUIRED": True,
            "CANONICAL_STATUS": "PARTIAL",
            "EVIDENCE": "Phase116/117/118; MT5 public Symbols Ticks UI docs; Phase118 export proves method works for recent window",
            "RESEARCH_DATE": RESEARCH_DATE,
            "class": "A",
        },
        {
            "SOURCE_NAME": "LITEFINANCE_MT5_COPY_TICKS_RANGE",
            "SOURCE_TYPE": "broker_api",
            "SYMBOL_AVAILABLE": CANONICAL_SYMBOL,
            "EXACT_XAUUSD_I_IDENTITY": "VERIFIED",
            "BID_AVAILABLE": "VERIFIED",
            "ASK_AVAILABLE": "VERIFIED",
            "TIMESTAMP_PRECISION": "millisecond",
            "HISTORICAL_RANGE": "UNKNOWN (depends on same history server; Phase37/38 gold pulls hung)",
            "2026_01_21_COVERAGE": "UNKNOWN",
            "FULL_REQUIRED_RANGE": "UNKNOWN",
            "LITEFINANCE_FEED_EQUIVALENCE": "VERIFIED",
            "ACCESS_METHOD": "MetaTrader5.copy_ticks_range (NOT executed in this phase)",
            "CREDENTIAL_REQUIRED": True,
            "PAYMENT_REQUIRED": False,
            "OPERATOR_ACTION_REQUIRED": True,
            "CANONICAL_STATUS": "PARTIAL",
            "EVIDENCE": "Phase116 CODE/PUBLIC-DOC; API exists but cannot overcome missing server retention",
            "RESEARCH_DATE": RESEARCH_DATE,
            "class": "A",
        },
        {
            "SOURCE_NAME": "LITEFINANCE_SUPPORT_HISTORICAL_ARCHIVE",
            "SOURCE_TYPE": "broker_support_archive",
            "SYMBOL_AVAILABLE": CANONICAL_SYMBOL,
            "EXACT_XAUUSD_I_IDENTITY": "NOT_PROVEN",
            "BID_AVAILABLE": "UNKNOWN",
            "ASK_AVAILABLE": "UNKNOWN",
            "TIMESTAMP_PRECISION": "UNKNOWN",
            "HISTORICAL_RANGE": "UNKNOWN",
            "2026_01_21_COVERAGE": "UNKNOWN",
            "FULL_REQUIRED_RANGE": "UNKNOWN",
            "LITEFINANCE_FEED_EQUIVALENCE": "NOT_PROVEN",
            "ACCESS_METHOD": "Operator contact LiteFinance support / LiveChat",
            "CREDENTIAL_REQUIRED": True,
            "PAYMENT_REQUIRED": "UNKNOWN",
            "OPERATOR_ACTION_REQUIRED": True,
            "CANONICAL_STATUS": "UNKNOWN",
            "EVIDENCE": "No public LiteFinance tick-archive catalog found; FAQ does not document tick dump procedure",
            "RESEARCH_DATE": RESEARCH_DATE,
            "class": "B",
        },
        {
            "SOURCE_NAME": "LITEFINANCE_TKC_TICK_CACHE",
            "SOURCE_TYPE": "local_terminal_cache",
            "SYMBOL_AVAILABLE": CANONICAL_SYMBOL,
            "EXACT_XAUUSD_I_IDENTITY": "VERIFIED",
            "BID_AVAILABLE": "VERIFIED",
            "ASK_AVAILABLE": "VERIFIED",
            "TIMESTAMP_PRECISION": "millisecond",
            "HISTORICAL_RANGE": "UNKNOWN / only months previously synchronized",
            "2026_01_21_COVERAGE": "UNKNOWN",
            "FULL_REQUIRED_RANGE": "UNKNOWN",
            "LITEFINANCE_FEED_EQUIVALENCE": "VERIFIED",
            "ACCESS_METHOD": "Operator terminal bases/server/ticks/XAUUSD_i/*.tkc after sync (not inspected/live-touched here)",
            "CREDENTIAL_REQUIRED": True,
            "PAYMENT_REQUIRED": False,
            "OPERATOR_ACTION_REQUIRED": True,
            "CANONICAL_STATUS": "PARTIAL",
            "EVIDENCE": "Phase116 MetaQuotes tick storage docs; no repo-accessible TKC covering missing window",
            "RESEARCH_DATE": RESEARCH_DATE,
            "class": "A",
        },
        {
            "SOURCE_NAME": "PHASE118_OPERATOR_EXPORT",
            "SOURCE_TYPE": "existing_project_artifact",
            "SYMBOL_AVAILABLE": CANONICAL_SYMBOL,
            "EXACT_XAUUSD_I_IDENTITY": "VERIFIED",
            "BID_AVAILABLE": "VERIFIED",
            "ASK_AVAILABLE": "VERIFIED",
            "TIMESTAMP_PRECISION": "millisecond",
            "HISTORICAL_RANGE": f"{PHASE118_FIRST} -> {PHASE118_LAST}",
            "2026_01_21_COVERAGE": "FALSE",
            "FULL_REQUIRED_RANGE": "FALSE",
            "LITEFINANCE_FEED_EQUIVALENCE": "VERIFIED",
            "ACCESS_METHOD": f"local file under {RAW_DROP_REL}",
            "CREDENTIAL_REQUIRED": False,
            "PAYMENT_REQUIRED": False,
            "OPERATOR_ACTION_REQUIRED": False,
            "CANONICAL_STATUS": "PARTIAL",
            "EVIDENCE": "Phase118 forensic validation; SHA256=" + EXPECTED_RAW_SHA256,
            "RESEARCH_DATE": RESEARCH_DATE,
            "class": "A",
        },
        {
            "SOURCE_NAME": "DUKASCOPY_XAUUSD_TICKS",
            "SOURCE_TYPE": "third_party_vendor",
            "SYMBOL_AVAILABLE": "XAUUSD",
            "EXACT_XAUUSD_I_IDENTITY": "REJECTED",
            "BID_AVAILABLE": "VERIFIED",
            "ASK_AVAILABLE": "VERIFIED",
            "TIMESTAMP_PRECISION": "tick/millisecond-class",
            "HISTORICAL_RANGE": "public docs from ~2003-05-05 through present",
            "2026_01_21_COVERAGE": "TRUE (generic only)",
            "FULL_REQUIRED_RANGE": "TRUE (generic only)",
            "LITEFINANCE_FEED_EQUIVALENCE": "NOT_PROVEN",
            "ACCESS_METHOD": "public historical data feed / export (NOT acquired here)",
            "CREDENTIAL_REQUIRED": False,
            "PAYMENT_REQUIRED": False,
            "OPERATOR_ACTION_REQUIRED": False,
            "CANONICAL_STATUS": "REJECTED",
            "EVIDENCE": "Phase116; substitution_verdict(generic_XAUUSD)=REJECTED; EV-EQ-01 NOT_PROVEN",
            "RESEARCH_DATE": RESEARCH_DATE,
            "class": "C",
        },
        {
            "SOURCE_NAME": "HISTDATA_XAUUSD",
            "SOURCE_TYPE": "third_party_vendor",
            "SYMBOL_AVAILABLE": "XAU/USD",
            "EXACT_XAUUSD_I_IDENTITY": "REJECTED",
            "BID_AVAILABLE": "VERIFIED",
            "ASK_AVAILABLE": "VERIFIED",
            "TIMESTAMP_PRECISION": "millisecond claimed",
            "HISTORICAL_RANGE": "monthly archives (generic)",
            "2026_01_21_COVERAGE": "UNKNOWN",
            "FULL_REQUIRED_RANGE": "UNKNOWN",
            "LITEFINANCE_FEED_EQUIVALENCE": "NOT_PROVEN",
            "ACCESS_METHOD": "public ZIP download (NOT acquired here)",
            "CREDENTIAL_REQUIRED": False,
            "PAYMENT_REQUIRED": False,
            "OPERATOR_ACTION_REQUIRED": False,
            "CANONICAL_STATUS": "REJECTED",
            "EVIDENCE": "Phase116",
            "RESEARCH_DATE": RESEARCH_DATE,
            "class": "C",
        },
        {
            "SOURCE_NAME": "MT5_TESTER_GENERATED_TICKS",
            "SOURCE_TYPE": "synthetic",
            "SYMBOL_AVAILABLE": CANONICAL_SYMBOL,
            "EXACT_XAUUSD_I_IDENTITY": "REJECTED",
            "BID_AVAILABLE": "PARTIAL",
            "ASK_AVAILABLE": "PARTIAL",
            "TIMESTAMP_PRECISION": "generated inside M1 bar",
            "HISTORICAL_RANGE": "if M1 exists",
            "2026_01_21_COVERAGE": "REJECTED",
            "FULL_REQUIRED_RANGE": "REJECTED",
            "LITEFINANCE_FEED_EQUIVALENCE": "REJECTED",
            "ACCESS_METHOD": "Strategy Tester",
            "CREDENTIAL_REQUIRED": True,
            "PAYMENT_REQUIRED": False,
            "OPERATOR_ACTION_REQUIRED": False,
            "CANONICAL_STATUS": "REJECTED",
            "EVIDENCE": "Phase116; synthetic/tester ticks forbidden",
            "RESEARCH_DATE": RESEARCH_DATE,
            "class": "E",
        },
    ]
    return rows

def support_request_template() -> dict[str, Any]:
    return {
        "title": "LiteFinance support request - historical REAL CLASSIC XAUUSD_i ticks",
        "submitted_by_this_phase": False,
        "to": "LiteFinance Support / LiveChat (operator-only)",
        "subject": "Request for historical REAL CLASSIC XAUUSD_i tick bid/ask dump",
        "body": (
            "Please provide a historical tick-by-tick dump for LiteFinance REAL CLASSIC "
            f"symbol {CANONICAL_SYMBOL} (exact symbol name required; not XAUUSD, GOLD, or GOLDUSD).\n\n"
            "Required range (UTC):\n"
            f"  start = {ACQ_START_ISO}\n"
            f"  end   = {ACQ_END_ISO}\n\n"
            "Required fields:\n"
            "  timestamp_utc, bid, ask\n"
            "Preferred optional fields:\n"
            "  last, volume, flags\n\n"
            "Please confirm:\n"
            f"1) The dump is from the LiteFinance {CANONICAL_SYMBOL} trading feed (CLASSIC REAL).\n"
            "2) Rows are actual historical bid/ask quote updates (not Strategy Tester generated ticks).\n"
            "3) Timestamps are UTC or provide the exact timezone for conversion.\n"
            f"4) Whether the critical timestamp {OUTLIER_TS} is included.\n"
            "5) File format (CSV/TSV/Parquet), approximate size, and delivery method.\n\n"
            "Background: an operator MT5 Symbols->Ticks export for XAUUSD_i only returned "
            f"{PHASE118_FIRST} through {PHASE118_LAST}. We need the missing earlier history "
            f"from {MISSING_START} through {MISSING_END}."
        ),
        "mandatory_critical_date": OUTLIER_TS,
        "do_not_auto_submit": True,
        "do_not_share_credentials_with_research_process": True,
    }


def mt5_capability_assessment() -> dict[str, Any]:
    return {
        "MT5_TICKS_REQUEST_STATUS": "PARTIAL",
        "ui_capability": (
            "VERIFIED that Symbols->Ticks->Request->Export exists and returned real "
            "XAUUSD_i ticks for a recent window (Phase118)."
        ),
        "server_retention": "UNKNOWN - LiteFinance does not publicly publish XAUUSD_i tick retention depth",
        "phase118_measured_window": f"{PHASE118_FIRST} -> {PHASE118_LAST}",
        "can_claim_pre_2026_07_23": False,
        "COPY_TICKS_RANGE_STATUS": "PARTIAL",
        "copy_ticks_range": {
            "api_capability": "EXISTS (MetaTrader5.copy_ticks_range)",
            "requires_connection": True,
            "executed_in_phase119": False,
            "depends_on_server_history": True,
            "can_overcome_missing_retention": False,
            "same_broker_feed_if_connected_to_LiteFinance_CLASSIC": True,
            "note": "API capability != data availability",
        },
        "CACHE_SOURCE_STATUS": "UNKNOWN",
        "cache_note": (
            "No repo-accessible TKC covering the missing window. Live MT5 bases were not inspected "
            "or modified. Cache only contains what was previously synchronized."
        ),
        "SUPPORT_ARCHIVE_STATUS": "UNKNOWN",
        "support_note": (
            "No public LiteFinance documentation of a tick-history archive catalog was found. "
            "Support contact remains a plausible but unverified path."
        ),
    }


def decision_matrix(local_rows: list[dict[str, Any]], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = []
    for src in catalog:
        action = "RESEARCH_ONLY"
        status = src["CANONICAL_STATUS"]
        if status == "REJECTED":
            action = "REJECT"
        elif src["SOURCE_NAME"] == "LITEFINANCE_SUPPORT_HISTORICAL_ARCHIVE":
            action = "OPERATOR_CONTACT_REQUIRED"
        elif src["SOURCE_NAME"] in {
            "LITEFINANCE_MT5_SYMBOLS_TICKS_TAB_EXPORT",
            "LITEFINANCE_MT5_COPY_TICKS_RANGE",
            "LITEFINANCE_TKC_TICK_CACHE",
        }:
            action = "OPERATOR_EXPORT_REQUIRED"
        elif src["SOURCE_NAME"] == "PHASE118_OPERATOR_EXPORT":
            action = "RESEARCH_ONLY"  # already ingested; insufficient alone
        matrix.append(
            {
                "OPTION": src["SOURCE_NAME"],
                "SOURCE": src["SOURCE_TYPE"],
                "EXACT_SYMBOL": src["SYMBOL_AVAILABLE"],
                "FULL_RANGE": src["FULL_REQUIRED_RANGE"],
                "OUTLIER_COVERAGE": src["2026_01_21_COVERAGE"],
                "BID_ASK": f"{src['BID_AVAILABLE']}/{src['ASK_AVAILABLE']}",
                "CHRONOLOGY_CAPABLE": "YES" if src["BID_AVAILABLE"] == "VERIFIED" and src["ASK_AVAILABLE"] == "VERIFIED" and status != "REJECTED" else "NO",
                "PROVENANCE": src["LITEFINANCE_FEED_EQUIVALENCE"],
                "ACCESS": src["ACCESS_METHOD"],
                "CANONICAL_STATUS": status,
                "ACTION": action,
                "class": src.get("class"),
            }
        )
    # local summary rows
    for loc in local_rows:
        if not loc.get("exists"):
            continue
        covers_missing = bool(loc.get("covers_missing_window"))
        matrix.append(
            {
                "OPTION": f"LOCAL::{loc['path']}",
                "SOURCE": "local_artifact",
                "EXACT_SYMBOL": CANONICAL_SYMBOL if loc.get("symbol_identity_ok") else "UNKNOWN",
                "FULL_RANGE": covers_missing,
                "OUTLIER_COVERAGE": loc.get("covers_outlier"),
                "BID_ASK": f"{loc.get('bid_available')}/{loc.get('ask_available')}",
                "CHRONOLOGY_CAPABLE": bool(loc.get("bid_available") and loc.get("ask_available")),
                "PROVENANCE": "VERIFIED" if loc.get("symbol_identity_ok") else "NOT_PROVEN",
                "ACCESS": "local_file",
                "CANONICAL_STATUS": loc.get("canonical_status"),
                "ACTION": "RESEARCH_ONLY" if loc.get("canonical_status") == "PARTIAL" else (
                    "PROCEED" if loc.get("canonical_status") == "VERIFIED" else "REJECT"
                ),
            }
        )
    return matrix


def event_coverage_projection(local_rows: list[dict[str, Any]]) -> dict[str, Any]:
    any_missing = any(r.get("covers_missing_window") for r in local_rows if r.get("exists"))
    any_outlier = any(r.get("covers_outlier") for r in local_rows if r.get("exists"))
    phase118 = next((r for r in local_rows if r.get("sha256") == EXPECTED_RAW_SHA256), None)
    return {
        "FULL_419_EVENT_COVERAGE_STATUS": "MISSING" if not any_missing else "PARTIAL",
        "AMBIGUOUS_394_COVERAGE_STATUS": "PARTIAL" if phase118 else "MISSING",
        "C_D_E_F_COVERAGE_STATUS": "PARTIAL_LATE_2026_ONLY",
        "OUTLIER_31_84R_SOURCE_STATUS": "MISSING",
        "OUTLIER_31_84R_COVERAGE": False if not any_outlier else True,
        "note": (
            "Only canonical XAUUSD_i sources counted. Generic XAUUSD vendors excluded from "
            "canonical coverage projection even if their documented range includes the outlier."
        ),
        "phase118_event_coverage_known": 12,
        "phase118_ambiguous_resolved_known": 12,
        "ambiguous_remaining_known": 382,
    }


def substitutions() -> dict[str, str]:
    return {
        "generic_XAUUSD": substitution_verdict("generic_XAUUSD"),
        "GOLD": substitution_verdict("GOLD"),
        "futures_gold": substitution_verdict("futures_gold"),
        "another_broker_XAUUSD": substitution_verdict("another_broker_XAUUSD"),
        "synthetic_bid_ask": substitution_verdict("synthetic_bid_ask"),
        "OHLC_derived_ticks": substitution_verdict("OHLC_derived_ticks"),
        "interpolated_ticks": substitution_verdict("interpolated_ticks"),
        "tester_generated_ticks": substitution_verdict("tester_generated_ticks"),
    }

def _frozen_integrity(root: Path) -> dict[str, Any]:
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    sha = file_sha256(root / PHASE40_SETUPS_JSONL)
    ts = p40.get("timestamp_utc")
    fp = p40.get("tape_fingerprint")
    ok = ts == PHASE40_TS and fp == FROZEN and sha == EXPECTED_JSONL_SHA256
    return {
        "ok": ok,
        "FROZEN_PHASE40_TIMESTAMP": ts,
        "FROZEN_PHASE40_FINGERPRINT": fp,
        "FROZEN_PHASE40_SHA256": sha,
        "expected_timestamp": PHASE40_TS,
        "expected_fingerprint": FROZEN,
        "expected_sha256": EXPECTED_JSONL_SHA256,
        "repaired": False,
    }


def _verify_phase118_raw_untouched(root: Path) -> dict[str, Any]:
    path = root / RAW_DROP_REL / "XAUUSD_i_202607230101_202609072009.csv"
    sha = file_sha256(path) if path.is_file() else None
    return {
        "path": str(path.relative_to(root)).replace("\\", "/") if path.is_file() else None,
        "present": path.is_file(),
        "sha256": sha,
        "matches_phase118": sha == EXPECTED_RAW_SHA256,
        "modified_by_phase119": False,
    }


def _patch_docs(root: Path, payload: dict[str, Any]) -> None:
    sot = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = sot.read_text(encoding="utf-8")
    line = (
        "Phase 119 (`docs/PHASE119_HISTORICAL_TICK_RECOVERY.md`) is research-only source resolution "
        "for missing pre-2026-07-23 LiteFinance XAUUSD_i ticks. It does not connect to MT5, read .env, "
        "download remote data, modify production, design exits, or start Phase 120. "
        f"CANONICAL_SOURCE_AVAILABLE={payload.get('CANONICAL_SOURCE_AVAILABLE')}; "
        f"DATA_ACQUIRED={payload.get('DATA_ACQUIRED')}."
    )
    if "PHASE119_HISTORICAL_TICK_RECOVERY" not in text:
        anchor = "Phase 118 (`docs/PHASE118_TICK_FORENSIC_VALIDATION.md`)"
        idx = text.find(anchor)
        if idx != -1:
            end = text.find("\n\n", idx)
            if end == -1:
                text = text.rstrip() + "\n\n" + line + "\n"
            else:
                text = text[:end] + "\n\n" + line + text[end:]
            sot.write_text(text, encoding="utf-8")

    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    needle = "`tradingbot/backtest/phase118_tick_forensic_validation.py`"
    if "phase119_historical_tick_recovery.py" not in btext and needle in btext:
        i = btext.find(needle)
        j = btext.find("\n", i)
        insert = (
            "\n`tradingbot/backtest/phase119_historical_tick_recovery.py` -- **RESEARCH_ONLY** "
            "historical tick source resolution; no MT5; no download; no .env."
        )
        bnd.write_text(btext[:j] + insert + btext[j:], encoding="utf-8")

    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 119 started | **NO** |", "| Phase 119 started | **YES** |")
    block = f"""

## Historical tick recovery (Phase 119)

| Claim | Status |
|---|---|
| PHASE119_STATUS | **{payload.get('PHASE119_STATUS')}** |
| SOURCE_RESEARCH_STATUS | **{payload.get('SOURCE_RESEARCH_STATUS')}** |
| CANONICAL_SOURCE_AVAILABLE | **{payload.get('CANONICAL_SOURCE_AVAILABLE')}** |
| FULL_HORIZON_SOURCE_STATUS | **{payload.get('FULL_HORIZON_SOURCE_STATUS')}** |
| OUTLIER_31_84R_COVERAGE | **{payload.get('OUTLIER_31_84R_COVERAGE')}** |
| ACQUISITION_STATUS | **{payload.get('ACQUISITION_STATUS')}** |
| DATA_ACQUIRED | **{'YES' if payload.get('DATA_ACQUIRED') else 'NO'}** |
| NEXT_ACTION | **{payload.get('NEXT_ACTION')}** |
| Canonical symbol | **XAUUSD_i** |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 120 started | **NO** |
"""
    marker = "## Historical tick recovery (Phase 119)"
    if marker in ktext:
        start = ktext.find(marker)
        ktext = ktext[:start].rstrip() + block
    else:
        ktext = ktext.rstrip() + block
    ku.write_text(ktext, encoding="utf-8")

    ledger = root / LEDGER_MD
    existing = ledger.read_text(encoding="utf-8") if ledger.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    extra = f"""

## Phase 119

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H119-01 | {today} | 119 | missing {MISSING_START}..{MISSING_END} | 419 | Phase116-118 | {payload.get('ACQUISITION_STATUS')} | reported | NO | operator support contact |

**FULL_HORIZON_SOURCE_STATUS:** `{payload.get('FULL_HORIZON_SOURCE_STATUS')}`
**CANONICAL_SOURCE_AVAILABLE:** `{payload.get('CANONICAL_SOURCE_AVAILABLE')}`
**NEXT_ACTION:** `{payload.get('NEXT_ACTION')}`
"""
    marker = "## Phase 119"
    if marker in existing:
        start = existing.find(marker)
        ledger.write_text(existing[:start].rstrip() + "\n" + extra, encoding="utf-8")
    else:
        ledger.write_text(existing.rstrip() + "\n" + extra, encoding="utf-8")


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    keys = [
        "PHASE119_STATUS", "SOURCE_RESEARCH_STATUS", "LOCAL_SOURCE_STATUS", "LITEFINANCE_SOURCE_STATUS",
        "LITEFINANCE_HISTORY_RETENTION_STATUS", "MT5_TICKS_REQUEST_STATUS", "COPY_TICKS_RANGE_STATUS",
        "CACHE_SOURCE_STATUS", "SUPPORT_ARCHIVE_STATUS", "THIRD_PARTY_SOURCE_STATUS",
        "EXACT_XAUUSD_I_SOURCE_STATUS", "FULL_HORIZON_SOURCE_STATUS", "MISSING_START", "MISSING_END",
        "OUTLIER_31_84R_SOURCE_STATUS", "OUTLIER_31_84R_COVERAGE", "FULL_419_EVENT_COVERAGE_STATUS",
        "AMBIGUOUS_394_COVERAGE_STATUS", "C_D_E_F_COVERAGE_STATUS", "CANONICAL_SOURCE_AVAILABLE",
        "CANONICAL_EQUIVALENCE_PROVEN", "ACQUISITION_STATUS", "OPERATOR_ACTION_REQUIRED", "NEXT_ACTION",
        "DATA_ACQUIRED", "RAW_DATA_PRESENT", "RAW_DATA_HASH", "TESTS_PHASE119",
        "REGRESSION_40_43_57_63_68_119", "FROZEN_PHASE40_TIMESTAMP", "FROZEN_PHASE40_FINGERPRINT",
        "FROZEN_PHASE40_SHA256",
    ]
    lines = [
        "# Phase 119 - Historical XAUUSD_i Tick Recovery & Source Resolution",
        "",
        "Research-only source resolution for missing pre-2026-07-23 LiteFinance XAUUSD_i ticks.",
        "No MT5 connection. No remote download. No production changes. Phase 120 not started.",
        "",
    ]
    for k in keys:
        lines.append(f"{k} = {payload.get(k)}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "DATA_ACQUIRED = false for Phase119 (no new historical dump). Phase118 raw export untouched.",
            "Generic XAUUSD / GOLD / synthetic / tester ticks remain non-canonical.",
            "",
            "## Operator support request",
            "",
            "See `support_request_template` in the JSON artifact. Do not auto-submit.",
            "",
        ]
    )
    (root / PHASE119_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_test_results(root: Path, phase119: dict[str, Any], regression: dict[str, Any]) -> None:
    path = root / PHASE119_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["TESTS_PHASE119"] = phase119
    payload["REGRESSION_40_43_57_63_68_119"] = regression
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = root / PHASE119_MD
    text = md.read_text(encoding="utf-8")
    text = re.sub(r"TESTS_PHASE119 = .*", f"TESTS_PHASE119 = {phase119}", text)
    text = re.sub(
        r"REGRESSION_40_43_57_63_68_119 = .*",
        f"REGRESSION_40_43_57_63_68_119 = {regression}",
        text,
    )
    md.write_text(text, encoding="utf-8")

def run_phase119_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    frozen = _frozen_integrity(root)
    prior = prior_phase_evidence(root)
    local_rows = local_source_inventory(root)
    catalog = source_catalog()
    caps = mt5_capability_assessment()
    matrix = decision_matrix(local_rows, catalog)
    projection = event_coverage_projection(local_rows)
    support = support_request_template()
    raw118 = _verify_phase118_raw_untouched(root)
    subs = substitutions()

    local_has_full = any(r.get("covers_missing_window") and r.get("canonical_status") == "VERIFIED" for r in local_rows)
    exact_methods_exist = True  # Symbols ticks / copy_ticks / phase118 prove identity methods
    canonical_available = False  # no verified FULL missing-window source
    equivalence_proven = False

    # Status synthesis
    local_status = "PARTIAL"  # verified local XAUUSD_i ticks exist but only late-2026
    if local_has_full:
        local_status = "VERIFIED"
        canonical_available = True
    litefinance_source = "PARTIAL"  # methods verified; missing-window data not obtained
    retention = "UNKNOWN"
    third_party = "REJECTED"
    exact_status = "PARTIAL"  # exact identity sources exist for recent data only
    full_horizon = "MISSING"
    acq = "OPERATOR_CONTACT_REQUIRED"
    next_action = "REQUEST_LITEFINANCE_XAUUSD_I_HISTORICAL_TICK_DUMP"
    operator_required = True

    status = "PASS" if frozen.get("ok") and raw118.get("matches_phase118") else "FAIL"

    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "PHASE119_STATUS": status,
        "SOURCE_RESEARCH_STATUS": "COMPLETE",
        "LOCAL_SOURCE_STATUS": local_status,
        "LITEFINANCE_SOURCE_STATUS": litefinance_source,
        "LITEFINANCE_HISTORY_RETENTION_STATUS": retention,
        "MT5_TICKS_REQUEST_STATUS": caps["MT5_TICKS_REQUEST_STATUS"],
        "COPY_TICKS_RANGE_STATUS": caps["COPY_TICKS_RANGE_STATUS"],
        "CACHE_SOURCE_STATUS": caps["CACHE_SOURCE_STATUS"],
        "SUPPORT_ARCHIVE_STATUS": caps["SUPPORT_ARCHIVE_STATUS"],
        "THIRD_PARTY_SOURCE_STATUS": third_party,
        "EXACT_XAUUSD_I_SOURCE_STATUS": exact_status,
        "FULL_HORIZON_SOURCE_STATUS": full_horizon,
        "MISSING_START": MISSING_START,
        "MISSING_END": MISSING_END,
        "OUTLIER_31_84R_SOURCE_STATUS": projection["OUTLIER_31_84R_SOURCE_STATUS"],
        "OUTLIER_31_84R_COVERAGE": projection["OUTLIER_31_84R_COVERAGE"],
        "FULL_419_EVENT_COVERAGE_STATUS": projection["FULL_419_EVENT_COVERAGE_STATUS"],
        "AMBIGUOUS_394_COVERAGE_STATUS": projection["AMBIGUOUS_394_COVERAGE_STATUS"],
        "C_D_E_F_COVERAGE_STATUS": projection["C_D_E_F_COVERAGE_STATUS"],
        "CANONICAL_SOURCE_AVAILABLE": canonical_available,
        "CANONICAL_EQUIVALENCE_PROVEN": equivalence_proven,
        "ACQUISITION_STATUS": acq,
        "OPERATOR_ACTION_REQUIRED": operator_required,
        "NEXT_ACTION": next_action,
        "DATA_ACQUIRED": False,
        "RAW_DATA_PRESENT": bool(raw118.get("present")),
        "RAW_DATA_HASH": raw118.get("sha256"),
        "phase118_raw_untouched": raw118,
        "prior_phase_evidence": prior,
        "local_sources": local_rows,
        "source_catalog": catalog,
        "mt5_capability": caps,
        "decision_matrix": matrix,
        "event_coverage_projection": projection,
        "support_request_template": support,
        "substitutions": subs,
        "n_events": N_EVENTS,
        "n_ambiguous_394": N_AMBIGUOUS_394,
        "canonical_symbol": CANONICAL_SYMBOL,
        "timezone": TZ,
        "exact_methods_exist": exact_methods_exist,
        "downloaded": False,
        "accounts_registered": False,
        "MT5_USED": False,
        "LIVE_TRADING": False,
        "ORDERS_PLACED": False,
        "ENV_ACCESSED": False,
        "PRODUCTION_CHANGED": False,
        "RISK_GATE_CHANGED": False,
        "TRADING_KERNEL_CHANGED": False,
        "EXECUTION_CHANGED": False,
        "STRATEGY_CHANGED": False,
        "CALIBRATION_CHANGED": False,
        "SIZING_CHANGED": False,
        "SLTP_CHANGED": False,
        "ML_ACTIVATED": False,
        "OPTIMIZATION_USED": False,
        "EXIT_DESIGN_SPEC_IMPLEMENTED": False,
        "TESTS_PHASE119": None,
        "REGRESSION_40_43_57_63_68_119": None,
        "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
        "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"),
        "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
        "frozen_integrity": frozen,
        "final_gate": "GO_OPERATOR_ACTION",
        "production_safety": {
            "MT5": "NOT_USED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "production_changes": "NONE",
            "exit_design": False,
            "DATA_ACQUIRED": False,
            "phase118_raw_modified": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE119_JSON, "md": PHASE119_MD, "ledger": LEDGER_MD},
        "phase120_started": False,
        "blocker": (
            f"No verified LiteFinance XAUUSD_i tick source covering {MISSING_START} -> {MISSING_END}; "
            f"outlier {OUTLIER_TS} remains uncovered; Phase118 export remains PARTIAL."
        ),
    }
    if not frozen.get("ok"):
        payload["PHASE119_STATUS"] = "FAIL"
        payload["blocker"] = "Frozen Phase 40 mismatch. File was not repaired."
    if raw118.get("present") and not raw118.get("matches_phase118"):
        payload["PHASE119_STATUS"] = "FAIL"
        payload["blocker"] = "Phase118 raw export hash mismatch; file was not repaired by this phase."

    (root / PHASE119_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE119_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    _write_md(root, payload)
    _patch_docs(root, payload)
    return payload


if __name__ == "__main__":
    run_phase119_collection(Path.cwd())