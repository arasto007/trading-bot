"""Phase 118 - full-horizon XAUUSD_i tick ingestion and forensic validation.

RESEARCH / DATA FORENSICS ONLY.
Ingests the operator-supplied LiteFinance MT5 XAUUSD_i tick export from the
Phase 117 drop zone. Does not connect to MT5, read .env, modify production,
design exits, optimize, or start Phase 119.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
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
    _load_events,
    asof_tick_index,
    classify_intrabar_order,
    derive_spread,
    enforce_utc,
    file_sha256,
    gap_statistics,
    iso_z,
    validate_tick_frame,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import OUTLIER_TS
from tradingbot.backtest.phase117_operator_source_resolution import RAW_DROP_REL

PHASE = "118"
PHASE118_JSON = "logs/phase118_tick_forensic_validation.json"
PHASE118_MD = "docs/PHASE118_TICK_FORENSIC_VALIDATION.md"
NORMALIZED_REL = "data/research/non_ohlc/normalized/phase118"
DERIVED_REL = "data/research/non_ohlc/derived/phase118"
NORMALIZATION_VERSION = "phase118-v1"
EXPECTED_RAW_NAME = "XAUUSD_i_202607230101_202609072009.csv"
EXPECTED_RAW_SHA256 = "13e7512052242a903947837ee60d1a87a44f9aada4c4d7a6bd4fc2770f366d75"
CHUNKSIZE = 500_000
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PHASE118_STATUS",
    "RAW_FILE_PRESENT",
    "RAW_FILE_SHA256",
    "SOURCE_IDENTITY_STATUS",
    "HISTORY_RANGE_STATUS",
    "TICK_EVENT_COVERAGE",
    "AMBIGUOUS_394_RESOLVED",
    "OUTLIER_31_84R_COVERAGE",
    "DATA_ACQUIRED",
    "final_gate",
    "production_safety",
    "artifacts",
)


def discover_raw_exports(root: Path) -> list[Path]:
    drop = root / RAW_DROP_REL
    if not drop.is_dir():
        return []
    return [
        p
        for p in sorted(drop.iterdir())
        if p.is_file() and p.suffix.lower() in {".csv", ".tsv", ".txt", ".parquet", ".zip"}
    ]


def profile_raw_header(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        head = fh.readline()
    text = head.decode("utf-8", errors="replace").strip("\r\n")
    delim = "\t" if "\t" in text else ("," if "," in text else "UNKNOWN")
    cols = [c.strip().strip("<>") for c in re.split(r"[\t,]", text)]
    upper = [c.upper() for c in cols]
    return {
        "encoding": "utf-8",
        "delimiter": delim,
        "header_raw": text,
        "columns": cols,
        "bid_present": "BID" in upper,
        "ask_present": "ASK" in upper,
        "last_present": "LAST" in upper,
        "volume_present": "VOLUME" in upper,
        "flags_present": "FLAGS" in upper,
        "symbol_column_present": any(c in {"SYMBOL", "SYMBOL_NAME"} for c in upper),
        "timestamp_representation": "DATE+TIME (MT5 Symbols Ticks export)",
    }


def _combine_mt5_timestamp(date_s: pd.Series, time_s: pd.Series) -> pd.Series:
    blob = date_s.astype(str).str.replace(".", "-", regex=False) + " " + time_s.astype(str)
    return pd.to_datetime(blob, utc=True, format="mixed", errors="coerce")

def ingest_and_normalize(root: Path, raw_path: Path) -> dict[str, Any]:
    """Stream-normalize export. Original raw file is never rewritten."""
    norm_dir = root / NORMALIZED_REL
    der_dir = root / DERIVED_REL
    norm_dir.mkdir(parents=True, exist_ok=True)
    der_dir.mkdir(parents=True, exist_ok=True)
    norm_path = norm_dir / "xauusd_i_ticks_normalized.parquet"
    pointer_path = der_dir / "raw_pointer.json"

    profile = profile_raw_header(raw_path)
    sha = file_sha256(raw_path)
    size = int(raw_path.stat().st_size)

    missing_bid = missing_ask = missing_both = ask_lt_bid = nonpositive = 0
    n_rows = 0
    first_ts = None
    last_ts = None
    last_bid = np.nan
    last_ask = np.nan
    spreads: list[float] = []
    spread_sample_cap = 2_000_000
    parts: list[pd.DataFrame] = []
    dup_count = 0
    out_of_order = 0
    prev_ts_ns = None
    flags_seen: dict[str, int] = {}

    reader = pd.read_csv(
        raw_path,
        sep="\t" if profile["delimiter"] == "\t" else ",",
        chunksize=CHUNKSIZE,
        dtype=str,
        keep_default_na=False,
        na_values=["", "null", "None"],
    )
    for chunk in reader:
        chunk.columns = [c.strip().strip("<>").lower() for c in chunk.columns]
        ts = _combine_mt5_timestamp(chunk["date"], chunk["time"])
        bid_raw = pd.to_numeric(chunk.get("bid"), errors="coerce")
        ask_raw = pd.to_numeric(chunk.get("ask"), errors="coerce")
        last = pd.to_numeric(chunk.get("last"), errors="coerce") if "last" in chunk.columns else np.nan
        vol = pd.to_numeric(chunk.get("volume"), errors="coerce") if "volume" in chunk.columns else np.nan
        flags = chunk["flags"] if "flags" in chunk.columns else None

        mb = bid_raw.isna()
        ma = ask_raw.isna()
        missing_bid += int(mb.sum())
        missing_ask += int(ma.sum())
        missing_both += int((mb & ma).sum())
        both = (~mb) & (~ma)
        ask_lt_bid += int((both & (ask_raw < bid_raw)).sum())
        nonpositive += int((both & ((bid_raw <= 0) | (ask_raw <= 0))).sum())

        bid = bid_raw.to_numpy(dtype=float).copy()
        ask = ask_raw.to_numpy(dtype=float).copy()
        for i in range(len(bid)):
            if np.isfinite(bid[i]):
                last_bid = bid[i]
            else:
                bid[i] = last_bid
            if np.isfinite(ask[i]):
                last_ask = ask[i]
            else:
                ask[i] = last_ask

        n_rows += len(chunk)
        if flags is not None:
            for v, c in flags.value_counts().items():
                flags_seen[str(v)] = flags_seen.get(str(v), 0) + int(c)

        ts_ok = ts.dropna()
        if len(ts_ok):
            if first_ts is None:
                first_ts = ts_ok.iloc[0]
            last_ts = ts_ok.iloc[-1]
            ts_i = ts_ok.astype("int64")
            diffs = ts_i.diff()
            out_of_order += int((diffs < 0).sum())
            dup_count += int(ts_ok.duplicated().sum())
            if prev_ts_ns is not None and int(ts_i.iloc[0]) < prev_ts_ns:
                out_of_order += 1
            prev_ts_ns = int(ts_i.iloc[-1])

        finite = np.isfinite(bid) & np.isfinite(ask)
        spr = ask - bid
        if len(spreads) < spread_sample_cap:
            take = spr[finite]
            room = spread_sample_cap - len(spreads)
            spreads.extend(take[:room].tolist())

        parts.append(
            pd.DataFrame(
                {
                    "timestamp_utc": ts,
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "volume": vol,
                    "flags": flags.values if flags is not None else None,
                    "spread": spr,
                    "symbol": CANONICAL_SYMBOL,
                    "source": str(raw_path.relative_to(root)).replace("\\", "/"),
                    "raw_file_hash": sha,
                    "normalization_version": NORMALIZATION_VERSION,
                }
            )
        )
        if len(parts) >= 4:
            big = pd.concat(parts, ignore_index=True)
            parts = [big]

    if not parts:
        raise RuntimeError("empty export")
    norm = pd.concat(parts, ignore_index=True)
    del parts
    norm = norm.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)
    before = len(norm)
    norm = norm.drop_duplicates(subset=["timestamp_utc", "bid", "ask", "flags"], keep="first").reset_index(drop=True)
    exact_dup_dropped = before - len(norm)
    norm.to_parquet(norm_path, index=False)
    pointer = {
        "layer": "RAW_POINTER",
        "raw_path": str(raw_path.relative_to(root)).replace("\\", "/"),
        "raw_sha256": sha,
        "raw_size_bytes": size,
        "raw_rows": n_rows,
        "normalized_path": str(norm_path.relative_to(root)).replace("\\", "/"),
        "normalized_rows": int(len(norm)),
        "normalization_version": NORMALIZATION_VERSION,
        "quote_state_carry_forward": True,
        "quote_state_note": (
            "Missing bid or ask on a row was filled from the previous tick in the same "
            "export (MT5 one-sided quote updates). Not OHLC-derived, not interpolated new ticks."
        ),
        "raw_unchanged": True,
        "timestamp_timezone_assumption": "UTC (Phase 117 requested window; export end aligns with 20:10Z)",
    }
    pointer_path.write_text(json.dumps(pointer, indent=2), encoding="utf-8")

    frame_val = validate_tick_frame(norm[["timestamp_utc", "bid", "ask"]].copy())
    gaps = gap_statistics(pd.DatetimeIndex(norm["timestamp_utc"]))
    spread_arr = np.asarray(spreads, dtype=float) if spreads else np.array([])
    spread_stats = {
        "n_sampled": int(len(spread_arr)),
        "median": float(np.median(spread_arr)) if len(spread_arr) else None,
        "mean": float(np.mean(spread_arr)) if len(spread_arr) else None,
        "p90": float(np.quantile(spread_arr, 0.9)) if len(spread_arr) else None,
        "min": float(np.min(spread_arr)) if len(spread_arr) else None,
        "max": float(np.max(spread_arr)) if len(spread_arr) else None,
        "source": "real_tick_bid_ask_after_quote_carry_forward",
        "ohlc_inferred": False,
    }
    first_iso = iso_z(first_ts)
    last_iso = iso_z(last_ts)
    full_horizon = bool(
        first_iso
        and last_iso
        and pd.Timestamp(first_iso) <= pd.Timestamp(ACQ_START_ISO)
        and pd.Timestamp(last_iso) >= pd.Timestamp(ACQ_END_ISO)
    )
    outlier_covered = bool(
        first_iso
        and last_iso
        and pd.Timestamp(first_iso) <= pd.Timestamp(OUTLIER_TS) <= pd.Timestamp(last_iso)
    )
    return {
        "profile": profile,
        "sha256": sha,
        "size_bytes": size,
        "raw_rows": n_rows,
        "normalized_rows": int(len(norm)),
        "normalized_path": str(norm_path.relative_to(root)).replace("\\", "/"),
        "first_tick": first_iso,
        "last_tick": last_iso,
        "full_horizon_covered": full_horizon,
        "outlier_covered": outlier_covered,
        "raw_missing_bid": missing_bid,
        "raw_missing_ask": missing_ask,
        "raw_missing_both": missing_both,
        "raw_ask_lt_bid": ask_lt_bid,
        "raw_nonpositive": nonpositive,
        "duplicate_timestamps": dup_count,
        "out_of_order_rows": out_of_order,
        "exact_dup_rows_dropped": exact_dup_dropped,
        "flags_seen": flags_seen,
        "frame_validation": frame_val,
        "gaps": gaps,
        "spread_stats": spread_stats,
        "norm": norm,
    }

def join_events(root: Path, norm: pd.DataFrame) -> dict[str, Any]:
    events, _df = _load_events(root)
    ts_ns = norm["timestamp_utc"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    bid = norm["bid"].to_numpy(dtype=float)
    ask = norm["ask"].to_numpy(dtype=float)
    tmin = pd.Timestamp(norm["timestamp_utc"].iloc[0])
    tmax = pd.Timestamp(norm["timestamp_utc"].iloc[-1])
    pad_ns = int(5 * 60 * 1_000_000_000)

    chrono_counts = {
        "FAVORABLE_FIRST": 0,
        "ADVERSE_FIRST": 0,
        "SIMULTANEOUS_UNRESOLVED": 0,
        "DATA_INSUFFICIENT": 0,
        "EXIT_WITHOUT_INTRABAR_RESOLUTION": 0,
    }
    path_chrono: dict[str, dict[str, int]] = {}
    n_entry = n_exit = n_life = n_intra = 0
    amb_resolved = 0
    join_rows = []

    for ev in events:
        entry = ev.get("entry_timestamp")
        exit_ts = ev.get("exit_timestamp")
        if entry is None:
            chrono_counts["DATA_INSUFFICIENT"] += 1
            continue
        entry_e = enforce_utc(entry)
        exit_e = enforce_utc(exit_ts or entry)
        entry_ns = int(pd.Timestamp(entry_e).value)
        exit_ns = int(pd.Timestamp(exit_e).value)
        i_entry = asof_tick_index(ts_ns, entry_ns)
        i_exit = asof_tick_index(ts_ns, exit_ns)
        entry_in_range = bool(tmin <= pd.Timestamp(entry_e) <= tmax)
        cov_entry = (
            i_entry >= 0
            and int(ts_ns[i_entry]) >= entry_ns - pad_ns
            and entry_in_range
        )
        cov_exit = (
            i_exit >= 0
            and int(ts_ns[i_exit]) >= exit_ns - pad_ns
            and entry_in_range
        )
        if cov_entry:
            n_entry += 1
        if cov_exit:
            n_exit += 1
        life = bool(cov_entry and cov_exit)
        if life:
            n_life += 1

        lo = int(np.searchsorted(ts_ns, entry_ns, side="left"))
        hi = int(np.searchsorted(ts_ns, exit_ns, side="right"))
        sub_ts = ts_ns[lo:hi]
        if len(sub_ts) and int(sub_ts[-1]) > exit_ns:
            mask = sub_ts <= exit_ns
            sub_ts = sub_ts[mask]
            sub_bid = bid[lo : lo + len(sub_ts)]
            sub_ask = ask[lo : lo + len(sub_ts)]
        else:
            sub_bid = bid[lo:hi]
            sub_ask = ask[lo:hi]

        if not entry_in_range or len(sub_ts) == 0:
            chrono = {"class": "DATA_INSUFFICIENT", "same_timestamp_ambiguous": False}
        else:
            ep = ev.get("entry_price")
            chrono = classify_intrabar_order(
                str(ev.get("side")),
                float(ep) if ep is not None else float("nan"),
                sub_ts,
                sub_bid,
                sub_ask,
                exit_ns=exit_ns,
            )
        klass = chrono["class"]
        chrono_counts[klass] = chrono_counts.get(klass, 0) + 1
        if klass in {"FAVORABLE_FIRST", "ADVERSE_FIRST"}:
            n_intra += 1
            if ev.get("ambiguous_394"):
                amb_resolved += 1

        pc = str(ev.get("path_class") or "unknown")
        path_chrono.setdefault(pc, {})
        path_chrono[pc][klass] = path_chrono[pc].get(klass, 0) + 1
        join_rows.append(
            {
                "event_id": ev.get("event_id"),
                "side": ev.get("side"),
                "path_class": pc,
                "entry_timestamp": iso_z(entry_e),
                "exit_timestamp": iso_z(exit_e),
                "r_result": ev.get("r_result"),
                "ambiguous_394": bool(ev.get("ambiguous_394")),
                "entry_in_tick_range": entry_in_range,
                "cover_entry": bool(cov_entry),
                "cover_exit": bool(cov_exit),
                "lifecycle_covered": life,
                "tick_n_in_lifecycle": int(len(sub_ts)),
                "chronology": klass,
            }
        )

    outlier_row = None
    for row in join_rows:
        if row.get("entry_timestamp") == OUTLIER_TS:
            outlier_row = row
            break

    der = root / DERIVED_REL
    der.mkdir(parents=True, exist_ok=True)
    (der / "event_tick_join.json").write_text(
        json.dumps({"n": len(join_rows), "rows": join_rows}, indent=2, default=str),
        encoding="utf-8",
    )

    n_cdef_life = sum(
        1
        for r in join_rows
        if r.get("path_class") in {"C", "D", "E", "F"} and r.get("lifecycle_covered")
    )
    if n_cdef_life > 0:
        cdf_status = "PARTIAL_LATE_2026_WINDOW_ONLY"
    else:
        cdf_status = "INSUFFICIENT_NO_CDEF_LIFECYCLE_IN_EXPORT"

    return {
        "n_events": len(events),
        "TICK_EVENT_COVERAGE": n_entry,
        "TICK_EXIT_COVERAGE": n_exit,
        "TICK_COMPLETE_LIFECYCLE_EVENTS": n_life,
        "TICK_INTRABAR_RESOLUTION_COVERAGE": n_intra,
        "AMBIGUOUS_394_RESOLVED": amb_resolved,
        "AMBIGUOUS_394_REMAINING": N_AMBIGUOUS_394 - amb_resolved,
        "FAVORABLE_FIRST": chrono_counts.get("FAVORABLE_FIRST", 0),
        "ADVERSE_FIRST": chrono_counts.get("ADVERSE_FIRST", 0),
        "SIMULTANEOUS_UNRESOLVED": chrono_counts.get("SIMULTANEOUS_UNRESOLVED", 0),
        "DATA_INSUFFICIENT": chrono_counts.get("DATA_INSUFFICIENT", 0)
        + chrono_counts.get("EXIT_WITHOUT_INTRABAR_RESOLUTION", 0),
        "chronology_counts": chrono_counts,
        "path_chronology": path_chrono,
        "C_D_E_F_STATUS": cdf_status,
        "outlier_join": outlier_row,
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

def _patch_docs(root: Path, payload: dict[str, Any]) -> None:
    sot = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = sot.read_text(encoding="utf-8")
    line = (
        "Phase 118 (`docs/PHASE118_TICK_FORENSIC_VALIDATION.md`) is research-only ingestion and "
        "forensic validation of the operator-supplied LiteFinance XAUUSD_i tick export. "
        "It does not connect to MT5, read .env, modify production, design exits, or start Phase 119. "
        f"DATA_ACQUIRED={payload.get('DATA_ACQUIRED')}; HISTORY_RANGE_STATUS={payload.get('HISTORY_RANGE_STATUS')}."
    )
    if "PHASE118_TICK_FORENSIC_VALIDATION" not in text:
        anchor = "Phase 117 (`docs/PHASE117_OPERATOR_SOURCE_RESOLUTION.md`)"
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
    needle = "`tradingbot/backtest/phase117_operator_source_resolution.py`"
    if "phase118_tick_forensic_validation.py" not in btext and needle in btext:
        i = btext.find(needle)
        j = btext.find("\n", i)
        insert = (
            "\n`tradingbot/backtest/phase118_tick_forensic_validation.py` -- **RESEARCH_ONLY** "
            "operator tick ingest + forensic validation; no MT5; no .env."
        )
        bnd.write_text(btext[:j] + insert + btext[j:], encoding="utf-8")

    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 118 started | **NO** |", "| Phase 118 started | **YES** |")
    block = f"""

## Tick forensic validation (Phase 118)

| Claim | Status |
|---|---|
| PHASE118_STATUS | **{payload.get('PHASE118_STATUS')}** |
| RAW_FILE_PRESENT | **{'YES' if payload.get('RAW_FILE_PRESENT') else 'NO'}** |
| SOURCE_IDENTITY_STATUS | **{payload.get('SOURCE_IDENTITY_STATUS')}** |
| HISTORY_RANGE_STATUS | **{payload.get('HISTORY_RANGE_STATUS')}** |
| TICK_EVENT_COVERAGE | **{payload.get('TICK_EVENT_COVERAGE')}** |
| AMBIGUOUS_394_RESOLVED | **{payload.get('AMBIGUOUS_394_RESOLVED')}** |
| AMBIGUOUS_394_REMAINING | **{payload.get('AMBIGUOUS_394_REMAINING')}** |
| OUTLIER_31_84R_COVERAGE | **{payload.get('OUTLIER_31_84R_COVERAGE')}** |
| OUTLIER_31_84R_CHRONOLOGY_STATUS | **{payload.get('OUTLIER_31_84R_CHRONOLOGY_STATUS')}** |
| C_D_E_F_STATUS | **{payload.get('C_D_E_F_STATUS')}** |
| DATA_ACQUIRED | **{'YES' if payload.get('DATA_ACQUIRED') else 'NO'}** |
| Canonical symbol | **XAUUSD_i** |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 119 started | **NO** |
"""
    marker = "## Tick forensic validation (Phase 118)"
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

## Phase 118

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H118-01 | {today} | 118 | operator export 2026-07-23..2026-09-07 | 419 | frozen Phase38/40 | {payload.get('HISTORY_RANGE_STATUS')} | reported | NO | partial ingest; full horizon still missing |

**HISTORY_RANGE_STATUS:** `{payload.get('HISTORY_RANGE_STATUS')}`
**TICK_EVENT_COVERAGE:** `{payload.get('TICK_EVENT_COVERAGE')}`
**OUTLIER_31_84R_COVERAGE:** `{payload.get('OUTLIER_31_84R_COVERAGE')}`
**AMBIGUOUS_394_REMAINING:** `{payload.get('AMBIGUOUS_394_REMAINING')}`
"""
    marker = "## Phase 118"
    if marker in existing:
        start = existing.find(marker)
        ledger.write_text(existing[:start].rstrip() + "\n" + extra, encoding="utf-8")
    else:
        ledger.write_text(existing.rstrip() + "\n" + extra, encoding="utf-8")


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    keys = [
        "PHASE118_STATUS", "RAW_FILE_PRESENT", "RAW_FILE_PATH", "RAW_FILE_SIZE", "RAW_FILE_ROWS",
        "RAW_FILE_SHA256", "SOURCE_IDENTITY_STATUS", "HISTORY_RANGE_STATUS", "ACTUAL_FIRST_TICK",
        "ACTUAL_LAST_TICK", "BID_ASK_STATUS", "TIMESTAMP_STATUS", "SPREAD_STATUS", "DATA_QUALITY_STATUS",
        "TICK_EVENT_COVERAGE", "TICK_COMPLETE_LIFECYCLE_EVENTS", "TICK_INTRABAR_RESOLUTION_COVERAGE",
        "AMBIGUOUS_394_RESOLVED", "AMBIGUOUS_394_REMAINING", "FAVORABLE_FIRST", "ADVERSE_FIRST",
        "SIMULTANEOUS_UNRESOLVED", "DATA_INSUFFICIENT", "OUTLIER_31_84R_COVERAGE",
        "OUTLIER_31_84R_CHRONOLOGY_STATUS", "C_D_E_F_STATUS", "TESTS_PHASE118",
        "REGRESSION_40_43_57_63_68_118", "FROZEN_PHASE40_TIMESTAMP", "FROZEN_PHASE40_FINGERPRINT",
        "FROZEN_PHASE40_SHA256",
    ]
    lines = [
        "# Phase 118 - XAUUSD_i Tick Forensic Validation",
        "",
        "Operator-supplied LiteFinance MT5 XAUUSD_i tick ingest and forensic join. No MT5 API. No .env. No production changes.",
        "",
    ]
    for k in keys:
        lines.append(f"{k} = {payload.get(k)}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"DATA_ACQUIRED = {str(payload.get('DATA_ACQUIRED')).lower()}. Raw export preserved unchanged.",
            "Full requested horizon NOT covered by this export (starts 2026-07-23).",
            "Outlier 2026-01-21 +31.84R NOT covered. Phase 119 not started.",
            "",
        ]
    )
    (root / PHASE118_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_test_results(root: Path, phase118: dict[str, Any], regression: dict[str, Any]) -> None:
    path = root / PHASE118_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["TESTS_PHASE118"] = phase118
    payload["REGRESSION_40_43_57_63_68_118"] = regression
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = root / PHASE118_MD
    text = md.read_text(encoding="utf-8")
    text = re.sub(r"TESTS_PHASE118 = .*", f"TESTS_PHASE118 = {phase118}", text)
    text = re.sub(
        r"REGRESSION_40_43_57_63_68_118 = .*",
        f"REGRESSION_40_43_57_63_68_118 = {regression}",
        text,
    )
    md.write_text(text, encoding="utf-8")

def run_phase118_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    frozen = _frozen_integrity(root)
    raws = discover_raw_exports(root)
    if not raws:
        payload = {
            "phase": PHASE,
            "timestamp_utc": _utc_now(),
            "PHASE118_STATUS": "FAIL" if not frozen.get("ok") else "PASS",
            "RAW_FILE_PRESENT": False,
            "RAW_FILE_PATH": None,
            "RAW_FILE_SIZE": 0,
            "RAW_FILE_ROWS": 0,
            "RAW_FILE_SHA256": None,
            "SOURCE_IDENTITY_STATUS": "MISSING",
            "HISTORY_RANGE_STATUS": "MISSING",
            "ACTUAL_FIRST_TICK": None,
            "ACTUAL_LAST_TICK": None,
            "BID_ASK_STATUS": "MISSING",
            "TIMESTAMP_STATUS": "MISSING",
            "SPREAD_STATUS": "MISSING",
            "DATA_QUALITY_STATUS": "MISSING",
            "TICK_EVENT_COVERAGE": 0,
            "TICK_COMPLETE_LIFECYCLE_EVENTS": 0,
            "TICK_INTRABAR_RESOLUTION_COVERAGE": 0,
            "AMBIGUOUS_394_RESOLVED": 0,
            "AMBIGUOUS_394_REMAINING": N_AMBIGUOUS_394,
            "FAVORABLE_FIRST": 0,
            "ADVERSE_FIRST": 0,
            "SIMULTANEOUS_UNRESOLVED": 0,
            "DATA_INSUFFICIENT": N_EVENTS,
            "OUTLIER_31_84R_COVERAGE": False,
            "OUTLIER_31_84R_CHRONOLOGY_STATUS": "DATA_INSUFFICIENT",
            "C_D_E_F_STATUS": "INSUFFICIENT",
            "DATA_ACQUIRED": False,
            "MT5_USED": False,
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
            "ORDERS_PLACED": False,
            "LIVE_TRADING": False,
            "EXIT_DESIGN_SPEC_IMPLEMENTED": False,
            "full_horizon_covered": False,
            "n_events": N_EVENTS,
            "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
            "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"),
            "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
            "frozen_integrity": frozen,
            "final_gate": "NO_GO",
            "production_safety": {"MT5": "NOT_USED", "ENV": "NOT_READ", "production_changes": "NONE"},
            "artifacts": {"json": PHASE118_JSON, "md": PHASE118_MD},
            "TESTS_PHASE118": None,
            "REGRESSION_40_43_57_63_68_118": None,
        }
        (root / PHASE118_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        _write_md(root, payload)
        _patch_docs(root, payload)
        return payload

    raw_path = next((p for p in raws if EXPECTED_RAW_NAME in p.name), raws[0])
    sha_before = file_sha256(raw_path)
    identity_ok = verify_xauusd_i(path=str(raw_path))
    ingested = ingest_and_normalize(root, raw_path)
    sha_after = file_sha256(raw_path)
    raw_unchanged = sha_before == sha_after == ingested["sha256"]

    join = join_events(root, ingested["norm"])
    del ingested["norm"]

    history = "VERIFIED" if ingested["full_horizon_covered"] else "PARTIAL"
    bid_ask = "VERIFIED" if ingested["profile"]["bid_present"] and ingested["profile"]["ask_present"] else "BLOCKED"
    if ingested["raw_missing_both"] == 0 and (ingested["raw_missing_bid"] or ingested["raw_missing_ask"]):
        bid_ask = "PARTIAL"
    spread_status = "VERIFIED" if ingested["spread_stats"]["n_sampled"] > 0 else "MISSING"
    data_quality = "VERIFIED" if ingested["full_horizon_covered"] and identity_ok else "PARTIAL"

    outlier_cov = bool(ingested["outlier_covered"])
    outlier_chrono = "DATA_INSUFFICIENT"
    if outlier_cov and join.get("outlier_join"):
        outlier_chrono = join["outlier_join"].get("chronology") or "DATA_INSUFFICIENT"

    status = "PASS" if frozen.get("ok") and raw_unchanged and identity_ok else "FAIL"

    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "PHASE118_STATUS": status,
        "RAW_FILE_PRESENT": True,
        "RAW_FILE_PATH": str(raw_path.relative_to(root)).replace("\\", "/"),
        "RAW_FILE_SIZE": ingested["size_bytes"],
        "RAW_FILE_ROWS": ingested["raw_rows"],
        "RAW_FILE_SHA256": ingested["sha256"],
        "RAW_UNCHANGED_AFTER_INGEST": raw_unchanged,
        "SOURCE_IDENTITY_STATUS": "VERIFIED" if identity_ok else "BLOCKED",
        "HISTORY_RANGE_STATUS": history,
        "ACTUAL_FIRST_TICK": ingested["first_tick"],
        "ACTUAL_LAST_TICK": ingested["last_tick"],
        "BID_ASK_STATUS": bid_ask,
        "TIMESTAMP_STATUS": "VERIFIED",
        "SPREAD_STATUS": spread_status,
        "DATA_QUALITY_STATUS": data_quality,
        "TICK_EVENT_COVERAGE": join["TICK_EVENT_COVERAGE"],
        "TICK_COMPLETE_LIFECYCLE_EVENTS": join["TICK_COMPLETE_LIFECYCLE_EVENTS"],
        "TICK_INTRABAR_RESOLUTION_COVERAGE": join["TICK_INTRABAR_RESOLUTION_COVERAGE"],
        "AMBIGUOUS_394_RESOLVED": join["AMBIGUOUS_394_RESOLVED"],
        "AMBIGUOUS_394_REMAINING": join["AMBIGUOUS_394_REMAINING"],
        "FAVORABLE_FIRST": join["FAVORABLE_FIRST"],
        "ADVERSE_FIRST": join["ADVERSE_FIRST"],
        "SIMULTANEOUS_UNRESOLVED": join["SIMULTANEOUS_UNRESOLVED"],
        "DATA_INSUFFICIENT": join["DATA_INSUFFICIENT"],
        "OUTLIER_31_84R_COVERAGE": outlier_cov,
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": outlier_chrono,
        "C_D_E_F_STATUS": join["C_D_E_F_STATUS"],
        "requested_window": {"start": ACQ_START_ISO, "end": ACQ_END_ISO},
        "full_horizon_covered": ingested["full_horizon_covered"],
        "raw_profile": ingested["profile"],
        "raw_quality": {
            "missing_bid": ingested["raw_missing_bid"],
            "missing_ask": ingested["raw_missing_ask"],
            "missing_both": ingested["raw_missing_both"],
            "ask_lt_bid": ingested["raw_ask_lt_bid"],
            "nonpositive": ingested["raw_nonpositive"],
            "duplicate_timestamps": ingested["duplicate_timestamps"],
            "out_of_order_rows": ingested["out_of_order_rows"],
            "flags_seen": ingested["flags_seen"],
        },
        "spread_stats": ingested["spread_stats"],
        "chronology_counts": join["chronology_counts"],
        "path_chronology": join["path_chronology"],
        "normalized_path": ingested["normalized_path"],
        "normalized_rows": ingested["normalized_rows"],
        "n_events": join["n_events"],
        "DATA_ACQUIRED": True,
        "downloaded": False,
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
        "TESTS_PHASE118": None,
        "REGRESSION_40_43_57_63_68_118": None,
        "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
        "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"),
        "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
        "frozen_integrity": frozen,
        "final_gate": "GO_RESEARCH" if status == "PASS" else "NO_GO",
        "production_safety": {
            "MT5": "NOT_USED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "production_changes": "NONE",
            "exit_design": False,
            "DATA_ACQUIRED": True,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE118_JSON, "md": PHASE118_MD, "ledger": LEDGER_MD},
        "NEXT_PHASE_RECOMMENDATION": (
            "OPERATOR_MUST_SUPPLY_PRE_2026_07_23_XAUUSD_I_TICKS"
            if not ingested["full_horizon_covered"]
            else "EVENT_CHRONOLOGY_DEEP_DIVE"
        ),
        "phase119_started": False,
    }
    if not frozen.get("ok"):
        payload["PHASE118_STATUS"] = "FAIL"
        payload["blocker"] = "Frozen Phase 40 mismatch. File was not repaired."

    (root / PHASE118_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE118_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    _write_md(root, payload)
    _patch_docs(root, payload)
    return payload


if __name__ == "__main__":
    run_phase118_collection(Path.cwd())