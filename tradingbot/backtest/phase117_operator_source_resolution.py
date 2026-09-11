"""Phase 117 - operator source resolution + controlled acquisition plan.

RESEARCH ONLY. Documents the exact LiteFinance CLASSIC -> MT5 -> XAUUSD_i ->
Ticks -> Export procedure and ingests operator-dropped raw exports if present.
Does not connect to MT5, read .env, download remotely, synthesize ticks,
modify production, implement an exit spec, or start Phase 118.
"""

from __future__ import annotations

import io
import json
import zipfile
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
from tradingbot.backtest.phase114_non_ohlc_acquisition_contract import (
    CANONICAL_SYMBOL,
    LOGICAL_SYMBOL,
    TZ,
)
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    EXPECTED_JSONL_SHA256,
    N_AMBIGUOUS_394,
    N_EVENTS,
    PHASE40_TS,
    derive_spread,
    file_sha256,
    gap_statistics,
    normalize_ticks,
    parse_tick_timestamps,
    validate_tick_frame,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import (
    OUTLIER_TS,
    PHASE116_JSON,
    substitution_verdict,
)

PHASE = "117"
PHASE117_JSON = "logs/phase117_operator_source_resolution.json"
PHASE117_MD = "docs/PHASE117_OPERATOR_SOURCE_RESOLUTION.md"
RAW_DROP_REL = "data/research/non_ohlc/raw/phase117_operator_export"
NORMALIZED_REL = "data/research/non_ohlc/normalized/phase117"
DERIVED_REL = "data/research/non_ohlc/derived/phase117"
NORMALIZATION_VERSION = "phase117-v1"
REJECT_SYMBOLS = frozenset({"XAUUSD", "GOLD", "GOLDUSD", "GOLD/USD", "XAU/USD"})
ALLOWED_EXPORT_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".parquet", ".zip"})
STATUS_VALUES = frozenset(
    {"VERIFIED", "PARTIAL", "UNKNOWN", "BLOCKED", "MISSING", "OPERATOR_ACTION_REQUIRED"}
)
NA_NO_RAW = "N/A_NO_RAW_EXPORT"
PHASE115_RESOLVED_AMBIGUOUS = 3
AMBIGUOUS_REMAINING_NO_RAW = N_AMBIGUOUS_394 - PHASE115_RESOLVED_AMBIGUOUS  # 391
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PHASE117_STATUS",
    "ACQUISITION_STATUS",
    "DATA_ACQUIRED",
    "operator_procedure",
    "final_gate",
    "production_safety",
    "artifacts",
)


def operator_procedure() -> dict[str, Any]:
    """Exact human-executable LiteFinance CLASSIC export procedure.

    This phase does not execute the procedure. executed_by_this_phase=False.
    """
    return {
        "title": "LiteFinance CLASSIC XAUUSD_i historical tick export",
        "executed_by_this_phase": False,
        "broker": "LiteFinance",
        "account_type": "CLASSIC",
        "path": [
            "LiteFinance CLASSIC",
            "MT5",
            "Symbols",
            "XAUUSD_i",
            "Ticks",
            f"Request {ACQ_START_ISO} to {ACQ_END_ISO}",
            "Export",
        ],
        "steps": [
            "Open the already-authorized LiteFinance CLASSIC MetaTrader 5 terminal (operator-local).",
            "Open Market Watch / Symbols.",
            f"Select exactly {CANONICAL_SYMBOL}. Reject {', '.join(sorted(REJECT_SYMBOLS))}.",
            "Open the Ticks tab for the selected symbol.",
            f"Request historical range start={ACQ_START_ISO} end={ACQ_END_ISO} (UTC).",
            f"Confirm the +31.84R outlier timestamp {OUTLIER_TS} falls inside the requested window.",
            "Export ticks to a local file (csv/tsv/txt/parquet preferred).",
            f"Place the unedited export under {RAW_DROP_REL}/ and do not overwrite prior acquisitions.",
            "Record SHA256, file size, export datetime, requested vs actual range, and timestamp precision.",
        ],
        "symbol_gate": {
            "accept": CANONICAL_SYMBOL,
            "reject": sorted(REJECT_SYMBOLS),
            "stop_if_unavailable": True,
            "silent_symbol_switch_forbidden": True,
        },
        "requested_start": ACQ_START_ISO,
        "requested_end": ACQ_END_ISO,
        "outlier_must_include": OUTLIER_TS,
        "required_fields_minimum": ["timestamp_utc", "bid", "ask"],
        "required_fields_preferred": ["timestamp_utc", "bid", "ask", "last", "volume", "flags"],
        "preferred_timestamp_precision": "millisecond",
        "export_formats": sorted(s.lstrip(".") for s in ALLOWED_EXPORT_SUFFIXES),
        "raw_preservation": {
            "immutable": True,
            "edit_forbidden": True,
            "hash_algorithm": "SHA256",
            "drop_directory": RAW_DROP_REL,
            "filename_convention": "XAUUSD_i_ticks_{requested_start}_{requested_end}_{export_utc}.csv",
        },
        "metadata_to_record": [
            "original_filename",
            "file_size_bytes",
            "sha256",
            "source",
            "symbol",
            "export_datetime_utc",
            "requested_start",
            "requested_end",
            "actual_first_tick",
            "actual_last_tick",
            "timestamp_precision",
            "export_row_count",
            "missing_intervals",
        ],
        "do_not_claim_full_history_until_operator_verifies": True,
        "do_not_connect_mt5_programmatically": True,
        "do_not_read_env": True,
        "substitutions": {
            "generic_XAUUSD": substitution_verdict("generic_XAUUSD"),
            "GOLD": substitution_verdict("GOLD"),
            "OHLC_derived_ticks": substitution_verdict("OHLC_derived_ticks"),
            "synthetic_bid_ask": substitution_verdict("synthetic_bid_ask"),
            "tester_generated_ticks": substitution_verdict("tester_generated_ticks"),
        },
    }


def discover_raw_exports(root: Path) -> list[dict[str, Any]]:
    """Scan only RAW_DROP_REL for operator exports. Creates the directory. Does not invent files."""
    root = Path(root)
    drop = root / RAW_DROP_REL
    drop.mkdir(parents=True, exist_ok=True)
    found: list[dict[str, Any]] = []
    for path in sorted(drop.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_EXPORT_SUFFIXES:
            continue
        found.append(
            {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "name": path.name,
                "suffix": path.suffix.lower(),
                "size_bytes": int(path.stat().st_size),
                "sha256": file_sha256(path),
                "xauusd_i_verified": verify_xauusd_i(symbol=None, path=path.name),
            }
        )
    return found


def _read_tabular(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf == ".parquet":
        return pd.read_parquet(path)
    if suf == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suf == ".txt":
        try:
            return pd.read_csv(path, sep="\t")
        except Exception:  # noqa: BLE001
            return pd.read_csv(path)
    if suf == ".csv":
        return pd.read_csv(path)
    if suf == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            members = [n for n in zf.namelist() if not n.endswith("/")]
            if not members:
                return pd.DataFrame()
            raw = zf.read(members[0])
            inner = Path(members[0])
            if inner.suffix.lower() == ".parquet":
                return pd.read_parquet(io.BytesIO(raw))
            if inner.suffix.lower() == ".tsv":
                return pd.read_csv(io.BytesIO(raw), sep="\t")
            return pd.read_csv(io.BytesIO(raw))
    raise ValueError(f"unsupported export suffix: {suf}")


def load_raw_tick_frame(path: Path) -> pd.DataFrame:
    """Load an operator export into a DataFrame. Does not mutate the raw file."""
    df = _read_tabular(Path(path))
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["timestamp_utc", "bid", "ask"])
    cols = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for want in ("timestamp_utc", "time_msc", "time", "timestamp", "bid", "ask", "last", "volume", "flags", "symbol"):
        if want in cols:
            rename[cols[want]] = want
    if rename:
        df = df.rename(columns=rename)
    return df


def validate_raw_export(
    df: pd.DataFrame,
    *,
    path: str | None = None,
    symbol: str | None = None,
    asof_state_utc: str | None = None,
) -> dict[str, Any]:
    """Validate operator raw export identity, schema, and no-future-leakage helpers."""
    verified = verify_xauusd_i(symbol=symbol, path=path)
    if symbol in REJECT_SYMBOLS:
        verified = False
    if "symbol" in df.columns and len(df):
        sample = str(df["symbol"].iloc[0])
        verified = verified and verify_xauusd_i(symbol=sample, path=path)
    work = df.copy()
    if "timestamp_utc" not in work.columns:
        work["timestamp_utc"] = parse_tick_timestamps(work)
    val = validate_tick_frame(work)
    ts = pd.to_datetime(work["timestamp_utc"], utc=True, errors="coerce")
    acq_start = pd.Timestamp(ACQ_START_ISO)
    acq_end = pd.Timestamp(ACQ_END_ISO)
    if acq_start.tzinfo is None:
        acq_start = acq_start.tz_localize("UTC")
    if acq_end.tzinfo is None:
        acq_end = acq_end.tz_localize("UTC")
    before = int((ts.notna() & (ts < acq_start)).sum())
    after = int((ts.notna() & (ts > acq_end)).sum())
    future_vs_asof = 0
    if asof_state_utc is not None:
        state = pd.Timestamp(asof_state_utc)
        if state.tzinfo is None:
            state = state.tz_localize("UTC")
        else:
            state = state.tz_convert("UTC")
        future_vs_asof = int((ts.notna() & (ts > state)).sum())
    outlier_ts = pd.Timestamp(OUTLIER_TS)
    if outlier_ts.tzinfo is None:
        outlier_ts = outlier_ts.tz_localize("UTC")
    outlier_in_window = bool(acq_start <= outlier_ts <= acq_end)
    outlier_covered = False
    if len(ts.dropna()):
        pad = pd.Timedelta(minutes=5)
        outlier_covered = bool(((ts >= outlier_ts) & (ts <= outlier_ts + pad)).any())
    spreads = []
    if "bid" in work.columns and "ask" in work.columns and len(work):
        for b, a in zip(work["bid"].tolist()[:5], work["ask"].tolist()[:5]):
            spreads.append(derive_spread(b, a))
    gaps = gap_statistics(pd.DatetimeIndex(ts.dropna()), weekday_threshold=None)
    return {
        "xauusd_i_verified": bool(verified),
        "symbol_rejected": bool(symbol in REJECT_SYMBOLS) if symbol else False,
        "validation": val,
        "n_rows": int(len(work)),
        "actual_first_tick": None if not len(ts.dropna()) else ts.min().isoformat().replace("+00:00", "Z"),
        "actual_last_tick": None if not len(ts.dropna()) else ts.max().isoformat().replace("+00:00", "Z"),
        "rows_before_requested_window": before,
        "rows_after_requested_window": after,
        "future_leakage_vs_asof": future_vs_asof,
        "no_future_leakage": future_vs_asof == 0,
        "outlier_in_requested_window": outlier_in_window,
        "outlier_tick_present": outlier_covered,
        "sample_spreads": spreads,
        "gaps": gaps,
        "timezone": TZ,
        "logical_symbol_forbidden": LOGICAL_SYMBOL,
    }


def classify_statuses(*, raw_present: bool, ingest: dict[str, Any] | None = None) -> dict[str, str]:
    """Status vocabulary: VERIFIED/PARTIAL/UNKNOWN/BLOCKED/MISSING/OPERATOR_ACTION_REQUIRED."""
    if not raw_present:
        return {
            "SOURCE_IDENTITY_STATUS": "UNKNOWN",
            "HISTORY_RANGE_STATUS": "UNKNOWN",
            "OUTLIER_COVERAGE_STATUS": "UNKNOWN",
            "BID_ASK_STATUS": "UNKNOWN",
            "TIMESTAMP_STATUS": "UNKNOWN",
            "EXPORT_STATUS": "MISSING",
            "RAW_INTEGRITY_STATUS": "MISSING",
            "ACQUISITION_STATUS": "OPERATOR_ACTION_REQUIRED",
            "SPREAD_STATUS": "UNKNOWN",
            "DATA_QUALITY_STATUS": "UNKNOWN",
        }
    ingest = ingest or {}
    verified = bool(ingest.get("xauusd_i_verified"))
    full = bool(ingest.get("full_window_covered"))
    outlier = bool(ingest.get("OUTLIER_31_84R_COVERAGE"))
    bid_ask_ok = bool(ingest.get("bid_ask_ok"))
    ts_ok = bool(ingest.get("timestamp_ok"))
    raw_ok = bool(ingest.get("raw_integrity_ok"))
    n_rows = int(ingest.get("n_rows") or 0)

    def _v(ok: bool, partial: bool = False) -> str:
        if ok:
            return "VERIFIED"
        if partial:
            return "PARTIAL"
        return "UNKNOWN"

    hist = "VERIFIED" if full else ("PARTIAL" if n_rows else "MISSING")
    if ingest.get("history_blocked"):
        hist = "BLOCKED"
    return {
        "SOURCE_IDENTITY_STATUS": "VERIFIED" if verified else ("BLOCKED" if n_rows else "UNKNOWN"),
        "HISTORY_RANGE_STATUS": hist,
        "OUTLIER_COVERAGE_STATUS": "VERIFIED" if outlier else ("MISSING" if n_rows else "UNKNOWN"),
        "BID_ASK_STATUS": _v(bid_ask_ok, partial=n_rows > 0),
        "TIMESTAMP_STATUS": _v(ts_ok, partial=n_rows > 0),
        "EXPORT_STATUS": "VERIFIED" if n_rows > 0 else "MISSING",
        "RAW_INTEGRITY_STATUS": "VERIFIED" if raw_ok else ("PARTIAL" if n_rows else "MISSING"),
        "ACQUISITION_STATUS": (
            "VERIFIED" if (verified and full and outlier and raw_ok) else "PARTIAL"
        ),
        "SPREAD_STATUS": _v(bid_ask_ok, partial=n_rows > 0),
        "DATA_QUALITY_STATUS": _v(bool(ingest.get("quality_ok")), partial=n_rows > 0),
    }


def _write_meta(path: Path, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


def ingest_if_present(root: Path) -> dict[str, Any]:
    """Ingest only if operator files exist under RAW_DROP_REL. Preserve raw unchanged."""
    root = Path(root)
    exports = discover_raw_exports(root)
    if not exports:
        statuses = classify_statuses(raw_present=False)
        return {
            "DATA_ACQUIRED": False,
            "RAW_DATA_PRESENT": False,
            "raw_exports": [],
            "RAW_DATA_HASH": None,
            "RAW_DATA_ROWS": 0,
            "ACTUAL_FIRST_TICK": None,
            "ACTUAL_LAST_TICK": None,
            "TICK_EVENT_COVERAGE": NA_NO_RAW,
            "TICK_COMPLETE_LIFECYCLE_EVENTS": NA_NO_RAW,
            "TICK_INTRABAR_RESOLUTION_COVERAGE": NA_NO_RAW,
            "AMBIGUOUS_394_RESOLVED": PHASE115_RESOLVED_AMBIGUOUS,
            "AMBIGUOUS_394_REMAINING": AMBIGUOUS_REMAINING_NO_RAW,
            "OUTLIER_31_84R_COVERAGE": False,
            "OUTLIER_31_84R_CHRONOLOGY_STATUS": "DATA_INSUFFICIENT",
            "full_window_covered": False,
            "statuses": statuses,
            "normalized_path": None,
            "derived_path": None,
        }

    preferred = [e for e in exports if e.get("xauusd_i_verified")] or list(exports)
    chosen = preferred[0]
    path = root / chosen["path"]
    raw_df = load_raw_tick_frame(path)
    v = validate_raw_export(
        raw_df,
        path=chosen["name"],
        symbol=CANONICAL_SYMBOL if chosen.get("xauusd_i_verified") else None,
    )
    if not v["xauusd_i_verified"]:
        statuses = classify_statuses(
            raw_present=True,
            ingest={
                "xauusd_i_verified": False,
                "n_rows": int(len(raw_df)),
                "full_window_covered": False,
                "OUTLIER_31_84R_COVERAGE": False,
                "bid_ask_ok": False,
                "timestamp_ok": False,
                "raw_integrity_ok": False,
                "quality_ok": False,
                "history_blocked": True,
            },
        )
        statuses["ACQUISITION_STATUS"] = "BLOCKED"
        statuses["SOURCE_IDENTITY_STATUS"] = "BLOCKED"
        return {
            "DATA_ACQUIRED": False,
            "RAW_DATA_PRESENT": True,
            "raw_exports": exports,
            "RAW_DATA_HASH": chosen.get("sha256"),
            "RAW_DATA_ROWS": int(len(raw_df)),
            "ACTUAL_FIRST_TICK": v.get("actual_first_tick"),
            "ACTUAL_LAST_TICK": v.get("actual_last_tick"),
            "TICK_EVENT_COVERAGE": 0,
            "TICK_COMPLETE_LIFECYCLE_EVENTS": 0,
            "TICK_INTRABAR_RESOLUTION_COVERAGE": 0,
            "AMBIGUOUS_394_RESOLVED": PHASE115_RESOLVED_AMBIGUOUS,
            "AMBIGUOUS_394_REMAINING": AMBIGUOUS_REMAINING_NO_RAW,
            "OUTLIER_31_84R_COVERAGE": False,
            "OUTLIER_31_84R_CHRONOLOGY_STATUS": "DATA_INSUFFICIENT",
            "full_window_covered": False,
            "validation": v,
            "statuses": statuses,
            "blocker": "Export present but XAUUSD_i identity not verified; generic symbols rejected.",
            "normalized_path": None,
            "derived_path": None,
        }

    norm = normalize_ticks(raw_df, source=chosen["path"], symbol=CANONICAL_SYMBOL)
    norm.attrs["normalization_version"] = NORMALIZATION_VERSION
    val = validate_tick_frame(norm)
    ts = (
        pd.DatetimeIndex(pd.to_datetime(norm["timestamp_utc"], utc=True))
        if len(norm)
        else pd.DatetimeIndex([], tz="UTC")
    )
    acq_start = pd.Timestamp(ACQ_START_ISO)
    acq_end = pd.Timestamp(ACQ_END_ISO)
    if acq_start.tzinfo is None:
        acq_start = acq_start.tz_localize("UTC")
    if acq_end.tzinfo is None:
        acq_end = acq_end.tz_localize("UTC")
    full = bool(len(ts) and ts.min() <= acq_start and ts.max() >= acq_end)
    outlier_ts = pd.Timestamp(OUTLIER_TS)
    if outlier_ts.tzinfo is None:
        outlier_ts = outlier_ts.tz_localize("UTC")
    outlier_cov = bool(len(ts) and (ts.min() <= outlier_ts <= ts.max()))
    history_blocked = bool(len(ts) and ts.max() < outlier_ts)

    norm_dir = root / NORMALIZED_REL
    der_dir = root / DERIVED_REL
    norm_dir.mkdir(parents=True, exist_ok=True)
    der_dir.mkdir(parents=True, exist_ok=True)
    out_parquet = norm_dir / "XAUUSD_i_ticks_normalized.parquet"
    norm.to_parquet(out_parquet, index=False)
    meta = {
        "source": chosen["path"],
        "symbol": CANONICAL_SYMBOL,
        "timezone": TZ,
        "acquisition_timestamp": _utc_now(),
        "normalization_version": NORMALIZATION_VERSION,
        "layer": "NORMALIZED",
        "raw_path": chosen["path"],
        "raw_sha256": chosen.get("sha256"),
        "requested_start": ACQ_START_ISO,
        "requested_end": ACQ_END_ISO,
        "actual_first_tick": None if not len(ts) else ts.min().isoformat().replace("+00:00", "Z"),
        "actual_last_tick": None if not len(ts) else ts.max().isoformat().replace("+00:00", "Z"),
        "raw_preserved_unedited": True,
    }
    _write_meta(out_parquet.with_suffix(".meta.json"), meta)
    derived = {
        "n_rows": int(len(norm)),
        "validation": val,
        "full_window_covered": full,
        "OUTLIER_31_84R_COVERAGE": outlier_cov,
        "gaps": gap_statistics(ts) if len(ts) else {},
        "raw_sha256": chosen.get("sha256"),
        "note": "Event-level joins deferred until full-horizon coverage is verified; no chronology claimed on incomplete data.",
    }
    der_path = der_dir / "ingest_summary.json"
    _write_meta(der_path, derived)

    ingest_flags = {
        "xauusd_i_verified": True,
        "n_rows": int(len(norm)),
        "full_window_covered": full,
        "OUTLIER_31_84R_COVERAGE": outlier_cov,
        "bid_ask_ok": int(val.get("missing_bid_rows") or 0) == 0
        and int(val.get("missing_ask_rows") or 0) == 0
        and int(len(norm)) > 0,
        "timestamp_ok": int(val.get("timezone_ambiguous") or 0) == 0 and int(len(norm)) > 0,
        "raw_integrity_ok": bool(chosen.get("sha256")),
        "quality_ok": bool(val.get("valid")),
        "history_blocked": history_blocked,
    }
    statuses = classify_statuses(raw_present=True, ingest=ingest_flags)
    if history_blocked:
        statuses["HISTORY_RANGE_STATUS"] = "BLOCKED"
        statuses["ACQUISITION_STATUS"] = "BLOCKED"

    return {
        "DATA_ACQUIRED": True,
        "RAW_DATA_PRESENT": True,
        "raw_exports": exports,
        "RAW_DATA_HASH": chosen.get("sha256"),
        "RAW_DATA_ROWS": int(len(norm)),
        "ACTUAL_FIRST_TICK": meta["actual_first_tick"],
        "ACTUAL_LAST_TICK": meta["actual_last_tick"],
        "TICK_EVENT_COVERAGE": "UNKNOWN_PENDING_EVENT_JOIN" if full else 0,
        "TICK_COMPLETE_LIFECYCLE_EVENTS": "UNKNOWN_PENDING_EVENT_JOIN" if full else 0,
        "TICK_INTRABAR_RESOLUTION_COVERAGE": "UNKNOWN_PENDING_EVENT_JOIN" if full else 0,
        "AMBIGUOUS_394_RESOLVED": PHASE115_RESOLVED_AMBIGUOUS,
        "AMBIGUOUS_394_REMAINING": AMBIGUOUS_REMAINING_NO_RAW,
        "OUTLIER_31_84R_COVERAGE": outlier_cov,
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": "DATA_INSUFFICIENT",
        "full_window_covered": full,
        "validation": v,
        "tick_validation": val,
        "statuses": statuses,
        "normalized_path": str(out_parquet.relative_to(root)).replace("\\", "/"),
        "derived_path": str(der_path.relative_to(root)).replace("\\", "/"),
        "xauusd_i_verified": True,
        "raw_integrity_ok": True,
    }


def _frozen_integrity(root: Path) -> dict[str, Any]:
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    sha = file_sha256(root / PHASE40_SETUPS_JSONL)
    ts = p40.get("timestamp_utc")
    fp = p40.get("tape_fingerprint") or p40.get("fingerprint")
    ok = ts == PHASE40_TS and fp == FROZEN and sha == EXPECTED_JSONL_SHA256
    return {
        "ok": ok,
        "FROZEN_PHASE40_TIMESTAMP": ts,
        "FROZEN_PHASE40_FINGERPRINT": fp,
        "FROZEN_PHASE40_SHA256": sha,
        "expected_timestamp": PHASE40_TS,
        "expected_fingerprint": FROZEN,
        "expected_sha256": EXPECTED_JSONL_SHA256,
        "jsonl_byte_identical": sha == EXPECTED_JSONL_SHA256,
        "repaired": False,
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phase 117 (`docs/PHASE117_OPERATOR_SOURCE_RESOLUTION.md`) is research-only operator "
        "source resolution for full-horizon XAUUSD_i ticks. It does not connect to MT5, read .env, "
        "download remotely, modify production, implement an exit spec, or start Phase 118."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    text = text.replace(
        "or start Phase 117.",
        "or claim Phase 117 acquisition without an operator export.",
    )
    if line not in text:
        marker = "Phase 116 (`docs/PHASE116_DATA_SOURCE_RESEARCH.md`)"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
        else:
            text = text.rstrip() + "\n\n" + line + "\n"
    src.write_text(text, encoding="utf-8")

    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase117_operator_source_resolution.py` -- **RESEARCH_ONLY** "
        "operator source resolution; no MT5; no .env; no Phase 118.\n"
    )
    needle = "`tradingbot/backtest/phase116_data_source_research.py`"
    if "phase117_operator_source_resolution.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")

    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 117 started | **NO** |", "| Phase 117 started | **YES** |")
    block = f"""

## Operator source resolution (Phase 117)

| Claim | Status |
|---|---|
| PHASE117_STATUS | **{payload.get("PHASE117_STATUS")}** |
| ACQUISITION_STATUS | **{payload.get("ACQUISITION_STATUS")}** |
| DATA_ACQUIRED | **{"YES" if payload.get("DATA_ACQUIRED") else "NO"}** |
| EXPORT_STATUS | **{payload.get("EXPORT_STATUS")}** |
| RAW_INTEGRITY_STATUS | **{payload.get("RAW_INTEGRITY_STATUS")}** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 117 started | **YES** |
| Phase 118 started | **NO** |
"""
    marker = "## Operator source resolution (Phase 117)"
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
        "## Phase 117",
        "",
        "| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| H117-01 | {today} | 117 | frozen Phase38/40 | 419 | event tape 419 resolved | {payload.get('ACQUISITION_STATUS')} | reported | NO | operator export; Phase 118 not started |",
        "",
        f"**PHASE117_STATUS:** `{payload.get('PHASE117_STATUS')}`",
        f"**ACQUISITION_STATUS:** `{payload.get('ACQUISITION_STATUS')}`",
        f"**DATA_ACQUIRED:** `{payload.get('DATA_ACQUIRED')}`",
        "",
    ]
    marker = "## Phase 117"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    keys = [
        "PHASE117_STATUS",
        "SOURCE_IDENTITY_STATUS",
        "HISTORY_RANGE_STATUS",
        "ACQUISITION_STATUS",
        "RAW_DATA_PRESENT",
        "RAW_DATA_HASH",
        "RAW_DATA_ROWS",
        "ACTUAL_FIRST_TICK",
        "ACTUAL_LAST_TICK",
        "TICK_EVENT_COVERAGE",
        "TICK_COMPLETE_LIFECYCLE_EVENTS",
        "TICK_INTRABAR_RESOLUTION_COVERAGE",
        "AMBIGUOUS_394_RESOLVED",
        "AMBIGUOUS_394_REMAINING",
        "OUTLIER_31_84R_COVERAGE",
        "OUTLIER_31_84R_CHRONOLOGY_STATUS",
        "BID_ASK_STATUS",
        "TIMESTAMP_STATUS",
        "SPREAD_STATUS",
        "DATA_QUALITY_STATUS",
        "EXPORT_STATUS",
        "RAW_INTEGRITY_STATUS",
        "REMAINING_UNKNOWN",
        "NEXT_PHASE_RECOMMENDATION",
        "TESTS_PHASE117",
        "REGRESSION_40_43_57_63_68_117",
        "FROZEN_PHASE40_TIMESTAMP",
        "FROZEN_PHASE40_FINGERPRINT",
        "FROZEN_PHASE40_SHA256",
        "MT5_USED",
        "LIVE_TRADING",
        "ORDERS_PLACED",
        "ENV_ACCESSED",
        "PRODUCTION_CHANGED",
        "DATA_ACQUIRED",
        "EXIT_DESIGN_SPEC_IMPLEMENTED",
    ]
    lines = [
        "# Phase 117 - Operator Source Resolution",
        "",
        "RESEARCH ONLY. Exact LiteFinance CLASSIC -> MT5 -> Symbols -> XAUUSD_i -> Ticks -> Export procedure.",
        "No programmatic MT5. No .env. No remote download. No Phase 118.",
        "",
    ]
    for k in keys:
        lines.append(f"{k} = {payload.get(k)}")
    lines.extend(
        [
            "",
            "## Operator procedure",
            "",
            "LiteFinance CLASSIC -> MT5 -> Symbols -> XAUUSD_i -> Ticks -> "
            f"Request {ACQ_START_ISO} to {ACQ_END_ISO} -> Export.",
            "",
            f"Symbol gate accepts only {CANONICAL_SYMBOL}; rejects XAUUSD/GOLD/GOLDUSD.",
            "Stop if XAUUSD_i is unavailable. Do not silently switch symbols.",
            "",
            f"Drop raw exports at `{RAW_DROP_REL}/`. Do not treat `data/XAUUSD_i_ticks_phase38.parquet` as Phase 117 acquisition.",
            "",
            "## Safety",
            "",
            "MT5_USED = False. ENV_ACCESSED = False. DATA_ACQUIRED is False unless an operator export is present.",
            "Exit design not implemented. Phase 118 was not started.",
            "",
        ]
    )
    (root / PHASE117_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_phase117_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    frozen = _frozen_integrity(root)
    proc = operator_procedure()
    ingest = ingest_if_present(root)
    statuses = ingest.get("statuses") or classify_statuses(raw_present=False)
    data_acquired = bool(ingest.get("DATA_ACQUIRED"))
    if not ingest.get("RAW_DATA_PRESENT"):
        data_acquired = False

    status = "PASS" if frozen.get("ok") else "FAIL"
    remaining = (
        "Full-horizon LiteFinance XAUUSD_i tick retention remains unproven until the operator "
        f"exports {ACQ_START_ISO}->{ACQ_END_ISO} into {RAW_DROP_REL}/. "
        f"Local Phase 115 sidecars are not Phase 117 acquisition. "
        f"Ambiguous remaining={AMBIGUOUS_REMAINING_NO_RAW}; outlier {OUTLIER_TS} uncovered without raw export."
    )
    next_rec = "PHASE118_NOT_STARTED"
    if not data_acquired:
        next_rec = "AWAIT_OPERATOR_XAUUSD_I_EXPORT"

    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": status,
        "PHASE117_STATUS": status,
        "SOURCE_IDENTITY_STATUS": statuses.get("SOURCE_IDENTITY_STATUS"),
        "HISTORY_RANGE_STATUS": statuses.get("HISTORY_RANGE_STATUS"),
        "OUTLIER_COVERAGE_STATUS": statuses.get("OUTLIER_COVERAGE_STATUS"),
        "BID_ASK_STATUS": statuses.get("BID_ASK_STATUS"),
        "TIMESTAMP_STATUS": statuses.get("TIMESTAMP_STATUS"),
        "EXPORT_STATUS": statuses.get("EXPORT_STATUS"),
        "RAW_INTEGRITY_STATUS": statuses.get("RAW_INTEGRITY_STATUS"),
        "ACQUISITION_STATUS": statuses.get("ACQUISITION_STATUS"),
        "SPREAD_STATUS": statuses.get("SPREAD_STATUS"),
        "DATA_QUALITY_STATUS": statuses.get("DATA_QUALITY_STATUS"),
        "RAW_DATA_PRESENT": bool(ingest.get("RAW_DATA_PRESENT")),
        "RAW_DATA_HASH": ingest.get("RAW_DATA_HASH"),
        "RAW_DATA_ROWS": ingest.get("RAW_DATA_ROWS"),
        "ACTUAL_FIRST_TICK": ingest.get("ACTUAL_FIRST_TICK"),
        "ACTUAL_LAST_TICK": ingest.get("ACTUAL_LAST_TICK"),
        "TICK_EVENT_COVERAGE": ingest.get("TICK_EVENT_COVERAGE"),
        "TICK_COMPLETE_LIFECYCLE_EVENTS": ingest.get("TICK_COMPLETE_LIFECYCLE_EVENTS"),
        "TICK_INTRABAR_RESOLUTION_COVERAGE": ingest.get("TICK_INTRABAR_RESOLUTION_COVERAGE"),
        "AMBIGUOUS_394_RESOLVED": ingest.get("AMBIGUOUS_394_RESOLVED"),
        "AMBIGUOUS_394_REMAINING": ingest.get("AMBIGUOUS_394_REMAINING"),
        "OUTLIER_31_84R_COVERAGE": ingest.get("OUTLIER_31_84R_COVERAGE"),
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": ingest.get("OUTLIER_31_84R_CHRONOLOGY_STATUS"),
        "REMAINING_UNKNOWN": remaining,
        "NEXT_PHASE_RECOMMENDATION": next_rec,
        "operator_procedure": proc,
        "ingest": {k: v for k, v in ingest.items() if k != "statuses"},
        "raw_drop_rel": RAW_DROP_REL,
        "normalized_rel": NORMALIZED_REL,
        "derived_rel": DERIVED_REL,
        "n_events": N_EVENTS,
        "window": {"start": ACQ_START_ISO, "end": ACQ_END_ISO, "outlier": OUTLIER_TS, "timezone": TZ},
        "canonical_symbol": CANONICAL_SYMBOL,
        "logical_symbol_rejected": LOGICAL_SYMBOL,
        "phase116_json": PHASE116_JSON,
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "data_acquired": data_acquired,
        "DATA_ACQUIRED": data_acquired,
        "remote_download": False,
        "ticks_synthesized": False,
        "ohlc_used_as_ticks": False,
        "intervention_implemented": False,
        "TESTS_PHASE117": None,
        "REGRESSION_40_43_57_63_68_117": None,
        "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
        "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"),
        "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
        "frozen_integrity": frozen,
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
        "PARAMETER_SEARCH_USED": False,
        "FINAL_GATE": "GO_RESEARCH" if frozen.get("ok") else "FAIL",
        "final_gate": "GO_RESEARCH" if frozen.get("ok") else "FAIL",
        "NEXT_RESEARCH_TARGET": next_rec,
        "evidence_kind": "OPERATOR-PROCEDURE + FROZEN-DATA-EVIDENCE",
        "hypotheses": [
            {
                "id": "H117-01",
                "claim": "An exact operator-executable LiteFinance XAUUSD_i tick export procedure can be documented and gated without connecting MT5 or fabricating acquisition.",
                "result": "SUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["operator_procedure", "raw_drop_scan", "frozen_integrity"],
        "oos_used_for_selection": False,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "MT5": "NOT_USED",
            "DATA_ACQUIRED": data_acquired,
            "production_changes": "NONE",
            "spec_implemented": False,
            "ticks_synthesized": False,
            "phase118_started": False,
        },
        "git_head": _git_head(root),
        "artifacts": {
            "json": PHASE117_JSON,
            "md": PHASE117_MD,
            "ledger": LEDGER_MD,
            "raw_drop": RAW_DROP_REL,
            "normalized": NORMALIZED_REL,
            "derived": DERIVED_REL,
        },
    }
    if not frozen.get("ok"):
        payload["PHASE117_STATUS"] = "FAIL"
        payload["blocker"] = "Frozen Phase 40 jsonl/fingerprint/timestamp mismatch. File was not repaired."

    for sk in (
        "SOURCE_IDENTITY_STATUS",
        "HISTORY_RANGE_STATUS",
        "OUTLIER_COVERAGE_STATUS",
        "BID_ASK_STATUS",
        "TIMESTAMP_STATUS",
        "EXPORT_STATUS",
        "RAW_INTEGRITY_STATUS",
        "ACQUISITION_STATUS",
        "SPREAD_STATUS",
        "DATA_QUALITY_STATUS",
    ):
        if payload.get(sk) not in STATUS_VALUES and payload.get(sk) is not None:
            payload[sk] = "UNKNOWN"

    (root / PHASE117_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE117_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    _write_md(root, payload)
    _patch_truth(root, payload)
    append_ledger(root, payload)
    return payload


def apply_test_results(root: Path, phase117: dict[str, Any], regression: dict[str, Any]) -> None:
    path = root / PHASE117_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["TESTS_PHASE117"] = phase117
    payload["REGRESSION_40_43_57_63_68_117"] = regression
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = root / PHASE117_MD
    text = md.read_text(encoding="utf-8")
    text = text.replace("TESTS_PHASE117 = None", f"TESTS_PHASE117 = {phase117}")
    text = text.replace(
        "REGRESSION_40_43_57_63_68_117 = None",
        f"REGRESSION_40_43_57_63_68_117 = {regression}",
    )
    md.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    out = run_phase117_collection(Path.cwd())
    print(out.get("PHASE117_STATUS"), out.get("ACQUISITION_STATUS"), out.get("DATA_ACQUIRED"))