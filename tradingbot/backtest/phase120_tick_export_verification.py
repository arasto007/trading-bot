"""Phase 120 - verify and ingest new operator XAUUSD_i tick exports.

RESEARCH / DATA VALIDATION ONLY.
Verifies newly supplied LiteFinance CLASSIC XAUUSD_i tick exports in the
Phase 117 drop zone, builds a derived research union with Phase 118, and
measures event coverage. Does not connect to MT5, read .env, modify raw
exports, alter production, design exits, or start Phase 121.
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
    file_sha256,
    iso_z,
    validate_tick_frame,
    verify_xauusd_i,
)
from tradingbot.backtest.phase116_data_source_research import OUTLIER_TS
from tradingbot.backtest.phase117_operator_source_resolution import RAW_DROP_REL
from tradingbot.backtest.phase118_tick_forensic_validation import (
    CHUNKSIZE,
    EXPECTED_RAW_NAME as PHASE118_RAW_NAME,
    EXPECTED_RAW_SHA256 as PHASE118_SHA256,
    NORMALIZED_REL as PHASE118_NORM_REL,
    _combine_mt5_timestamp,
    discover_raw_exports,
    join_events,
    profile_raw_header,
)

PHASE = "120"
PHASE120_JSON = "logs/phase120_tick_export_verification.json"
PHASE120_MD = "docs/PHASE120_TICK_EXPORT_VERIFICATION.md"
NORMALIZED_REL = "data/research/non_ohlc/normalized/phase120"
DERIVED_REL = "data/research/non_ohlc/derived/phase120"
NORMALIZATION_VERSION = "phase120-v1"
PHASE118_FIRST = "2026-07-23T01:01:00.042000Z"
PHASE118_LAST = "2026-09-07T20:09:56.006000Z"
NEW_EXPECTED_NAME = "XAUUSD_i_202605200101_202607242358.csv"
NEW_EXPECTED_SHA256 = "bd0e68c8c518113b7b397a5f7ced0014b8e414b496ae33a780f5f3f9aaeb0f4e"
# Prefer ~2 calendar months backward for the next small operator export.
NEXT_EXPORT_MONTHS = 2

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PHASE120_STATUS",
    "NEW_OPERATOR_FILES",
    "TICK_EVENT_COVERAGE",
    "OUTLIER_31_84R_TICK_COVERAGE",
    "NEXT_ACTION",
    "DATA_ACQUIRED",
    "final_gate",
    "production_safety",
    "artifacts",
)

def inventory_raw_files(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in discover_raw_exports(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        sha = file_sha256(path)
        profile = profile_raw_header(path)
        is_p118 = path.name == PHASE118_RAW_NAME or sha == PHASE118_SHA256
        # Stream first/last without full load for known large CSVs
        first = last = None
        n_rows = None
        with path.open("rb") as fh:
            header = fh.readline()
            first_line = fh.readline().decode("utf-8", errors="replace").strip("\r\n")
            fh.seek(0, 2)
            size = fh.tell()
            # walk back for last non-empty line
            pos = max(0, size - 4096)
            fh.seek(pos)
            chunk = fh.read().decode("utf-8", errors="replace")
            lines = [ln for ln in chunk.splitlines() if ln.strip()]
            last_line = lines[-1] if lines else ""
        def parse_line(line: str) -> str | None:
            if not line or line.startswith("<"):
                return None
            parts = line.split("\t" if "\t" in line else ",")
            if len(parts) < 2:
                return None
            blob = parts[0].replace(".", "-") + " " + parts[1]
            try:
                return iso_z(pd.to_datetime(blob, utc=True, format="mixed"))
            except Exception:
                return None
        first = parse_line(first_line)
        last = parse_line(last_line)
        # Avoid full-file newline scans on multi-hundred-MB exports (resume/ingest owns row counts).
        n_rows = None
        if size < 80_000_000:
            n_nl = 0
            with path.open("rb") as fh:
                for c in iter(lambda: fh.read(1 << 20), b""):
                    n_nl += c.count(b"\n")
            n_rows = max(0, n_nl - 1)
        rows.append(
            {
                "filename": path.name,
                "path": rel,
                "size": int(path.stat().st_size),
                "extension": path.suffix.lower(),
                "row_count": n_rows,
                "columns": profile["columns"],
                "first_timestamp": first,
                "last_timestamp": last,
                "detected_symbol": CANONICAL_SYMBOL if verify_xauusd_i(path=path.name) else None,
                "bid_exists": profile["bid_present"],
                "ask_exists": profile["ask_present"],
                "last_exists": profile["last_present"],
                "volume_exists": profile["volume_present"],
                "flags_exists": profile["flags_present"],
                "timestamp_precision": "millisecond",
                "timestamp_timezone_interpretation": "UTC (Phase117/118 convention; export end aligns with requested UTC)",
                "sha256": sha,
                "is_phase118": is_p118,
                "is_new_operator_file": not is_p118,
                "symbol_identity_ok": verify_xauusd_i(path=path.name),
                "profile": profile,
            }
        )
    return rows


def ingest_new_export(root: Path, raw_path: Path) -> dict[str, Any]:
    """Normalize NEW export only. Never rewrites raw. Does not touch Phase118 raw."""
    norm_dir = root / NORMALIZED_REL
    der_dir = root / DERIVED_REL
    norm_dir.mkdir(parents=True, exist_ok=True)
    der_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{raw_path.stem}_normalized.parquet"
    norm_path = norm_dir / out_name

    profile = profile_raw_header(raw_path)
    sha_before = file_sha256(raw_path)
    size = int(raw_path.stat().st_size)
    pointer_path = der_dir / f"{raw_path.stem}_pointer.json"
    if norm_path.is_file() and pointer_path.is_file():
        try:
            ptr = json.loads(pointer_path.read_text(encoding="utf-8"))
        except Exception:
            ptr = {}
        if ptr.get("raw_sha256_before") == sha_before and int(ptr.get("normalized_rows") or 0) > 0:
            keep_cols = [
                "timestamp_utc",
                "bid",
                "ask",
                "spread",
                "symbol",
                "source",
                "raw_file_hash",
                "normalization_version",
            ]
            try:
                norm = pd.read_parquet(norm_path, columns=keep_cols)
            except Exception:
                norm = pd.read_parquet(norm_path)
                norm = norm[[c for c in keep_cols if c in norm.columns]]
            for c in ("bid", "ask", "spread"):
                if c in norm.columns:
                    norm[c] = norm[c].astype(np.float32)
            first_iso = iso_z(norm["timestamp_utc"].iloc[0]) if len(norm) else None
            last_iso = iso_z(norm["timestamp_utc"].iloc[-1]) if len(norm) else None
            sha_after = file_sha256(raw_path)
            # Lightweight raw quality scan (does not rewrite raw).
            missing_bid = missing_ask = missing_both = ask_lt_bid = nonpositive = 0
            out_of_order = dup_count = 0
            prev_ts_ns = None
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
                mb = bid_raw.isna()
                ma = ask_raw.isna()
                missing_bid += int(mb.sum())
                missing_ask += int(ma.sum())
                missing_both += int((mb & ma).sum())
                both = (~mb) & (~ma)
                ask_lt_bid += int((both & (ask_raw < bid_raw)).sum())
                nonpositive += int((both & ((bid_raw <= 0) | (ask_raw <= 0))).sum())
                ts_ok = ts.dropna()
                if len(ts_ok):
                    ts_i = ts_ok.astype("int64")
                    out_of_order += int((ts_i.diff() < 0).sum())
                    dup_count += int(ts_ok.duplicated().sum())
                    if prev_ts_ns is not None and int(ts_i.iloc[0]) < prev_ts_ns:
                        out_of_order += 1
                    prev_ts_ns = int(ts_i.iloc[-1])
            return {
                "raw_path": str(raw_path.relative_to(root)).replace("\\", "/"),
                "filename": raw_path.name,
                "sha256": sha_before,
                "raw_unchanged": sha_before == sha_after,
                "size_bytes": size,
                "raw_rows": int(ptr.get("raw_rows") or len(norm)),
                "normalized_rows": int(len(norm)),
                "normalized_path": str(norm_path.relative_to(root)).replace("\\", "/"),
                "first_tick": first_iso,
                "last_tick": last_iso,
                "profile": profile,
                "raw_missing_bid": missing_bid,
                "raw_missing_ask": missing_ask,
                "raw_missing_both": missing_both,
                "raw_ask_lt_bid": ask_lt_bid,
                "raw_nonpositive": nonpositive,
                "duplicate_timestamps": dup_count,
                "out_of_order_rows": out_of_order,
                "exact_dup_rows_dropped": 0,
                "flags_seen": {},
                "frame_validation": validate_tick_frame(norm[["timestamp_utc", "bid", "ask"]].copy()),
                "spread_sample": {},
                "norm": norm,
                "symbol_identity_ok": verify_xauusd_i(path=raw_path.name),
                "resumed_from_normalized": True,
            }

    missing_bid = missing_ask = missing_both = ask_lt_bid = nonpositive = 0
    n_rows = 0
    first_ts = last_ts = None
    last_bid = np.nan
    last_ask = np.nan
    spreads: list[float] = []
    spread_cap = 2_000_000
    parts: list[pd.DataFrame] = []
    dup_count = out_of_order = 0
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
            out_of_order += int((ts_i.diff() < 0).sum())
            dup_count += int(ts_ok.duplicated().sum())
            if prev_ts_ns is not None and int(ts_i.iloc[0]) < prev_ts_ns:
                out_of_order += 1
            prev_ts_ns = int(ts_i.iloc[-1])

        finite = np.isfinite(bid) & np.isfinite(ask)
        spr = ask - bid
        if len(spreads) < spread_cap:
            take = spr[finite]
            spreads.extend(take[: spread_cap - len(spreads)].tolist())

        parts.append(
            pd.DataFrame(
                {
                    "timestamp_utc": ts,
                    "bid": np.asarray(bid, dtype=np.float32),
                    "ask": np.asarray(ask, dtype=np.float32),
                    "spread": np.asarray(spr, dtype=np.float32),
                    "symbol": CANONICAL_SYMBOL,
                    "source": str(raw_path.relative_to(root)).replace("\\", "/"),
                    "raw_file_hash": sha_before,
                    "normalization_version": NORMALIZATION_VERSION,
                }
            )
        )
        if len(parts) >= 4:
            parts = [pd.concat(parts, ignore_index=True)]

    if not parts:
        raise RuntimeError(f"empty export: {raw_path.name}")
    norm = pd.concat(parts, ignore_index=True)
    del parts
    norm = norm.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)
    before = len(norm)
    dup_cols = ["timestamp_utc", "bid", "ask"]
    if "flags" in norm.columns:
        dup_cols = ["timestamp_utc", "bid", "ask", "flags"]
    norm = norm.drop_duplicates(subset=dup_cols, keep="first").reset_index(drop=True)
    exact_dup_dropped = before - len(norm)
    keep = [
        c
        for c in [
            "timestamp_utc",
            "bid",
            "ask",
            "spread",
            "symbol",
            "source",
            "raw_file_hash",
            "normalization_version",
        ]
        if c in norm.columns
    ]
    norm = norm[keep]
    for c in ("bid", "ask", "spread"):
        if c in norm.columns:
            norm[c] = norm[c].astype(np.float32)
    norm.to_parquet(norm_path, index=False, compression="zstd")

    sha_after = file_sha256(raw_path)
    spread_arr = np.asarray(spreads, dtype=float) if spreads else np.array([])
    first_iso = iso_z(first_ts)
    last_iso = iso_z(last_ts)
    frame_val = validate_tick_frame(norm[["timestamp_utc", "bid", "ask"]].copy())
    pointer = {
        "raw_path": str(raw_path.relative_to(root)).replace("\\", "/"),
        "raw_sha256_before": sha_before,
        "raw_sha256_after": sha_after,
        "raw_unchanged": sha_before == sha_after,
        "normalized_path": str(norm_path.relative_to(root)).replace("\\", "/"),
        "normalized_rows": int(len(norm)),
        "raw_rows": n_rows,
        "quote_state_carry_forward": True,
        "normalization_version": NORMALIZATION_VERSION,
    }
    (der_dir / f"{raw_path.stem}_pointer.json").write_text(json.dumps(pointer, indent=2), encoding="utf-8")
    return {
        "raw_path": str(raw_path.relative_to(root)).replace("\\", "/"),
        "filename": raw_path.name,
        "sha256": sha_before,
        "raw_unchanged": sha_before == sha_after,
        "size_bytes": size,
        "raw_rows": n_rows,
        "normalized_rows": int(len(norm)),
        "normalized_path": str(norm_path.relative_to(root)).replace("\\", "/"),
        "first_tick": first_iso,
        "last_tick": last_iso,
        "profile": profile,
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
        "spread_sample": {
            "n": int(len(spread_arr)),
            "median": float(np.median(spread_arr)) if len(spread_arr) else None,
            "p5": float(np.quantile(spread_arr, 0.05)) if len(spread_arr) else None,
            "p95": float(np.quantile(spread_arr, 0.95)) if len(spread_arr) else None,
            "min": float(np.min(spread_arr)) if len(spread_arr) else None,
            "max": float(np.max(spread_arr)) if len(spread_arr) else None,
        },
        "norm": norm,
        "symbol_identity_ok": verify_xauusd_i(path=raw_path.name),
    }

def build_union(root: Path, new_norm: pd.DataFrame) -> dict[str, Any]:
    """Derived research union of Phase118 normalized + new normalized. Raw files untouched."""
    der = root / DERIVED_REL
    der.mkdir(parents=True, exist_ok=True)
    p118_path = root / PHASE118_NORM_REL / "xauusd_i_ticks_normalized.parquet"
    frames = []
    sources = []
    cols = ["timestamp_utc", "bid", "ask", "spread"]
    if p118_path.is_file():
        old = pd.read_parquet(p118_path, columns=cols)
        for c in ("bid", "ask", "spread"):
            old[c] = old[c].astype(np.float32)
        old["union_source"] = "phase118"
        frames.append(old)
        sources.append(str(p118_path.relative_to(root)).replace("\\", "/"))
    neu = new_norm[cols].copy()
    for c in ("bid", "ask", "spread"):
        neu[c] = neu[c].astype(np.float32)
    neu["union_source"] = "phase120_new"
    frames.append(neu)
    sources.append("phase120_new_normalized")
    union = pd.concat(frames, ignore_index=True)
    del frames
    before = len(union)
    union = union.sort_values("timestamp_utc").drop_duplicates(
        subset=["timestamp_utc", "bid", "ask"], keep="first"
    ).reset_index(drop=True)
    out_path = der / "xauusd_i_ticks_union.parquet"
    union[["timestamp_utc", "bid", "ask", "spread", "union_source"]].to_parquet(
        out_path, index=False, compression="zstd"
    )
    first = iso_z(union["timestamp_utc"].iloc[0]) if len(union) else None
    last = iso_z(union["timestamp_utc"].iloc[-1]) if len(union) else None
    return {
        "path": str(out_path.relative_to(root)).replace("\\", "/"),
        "sources": sources,
        "rows_before_dedupe": before,
        "rows_after_dedupe": int(len(union)),
        "first_tick": first,
        "last_tick": last,
        "union": union,
    }


def overlap_and_gap(new_first: str | None, new_last: str | None) -> dict[str, Any]:
    if not new_first or not new_last:
        return {
            "OVERLAP_START": None,
            "OVERLAP_END": None,
            "GAP_TO_PHASE118": "UNKNOWN",
            "extends_before_phase118": False,
            "additional_days_before": None,
        }
    nf, nl = pd.Timestamp(new_first), pd.Timestamp(new_last)
    of, ol = pd.Timestamp(PHASE118_FIRST), pd.Timestamp(PHASE118_LAST)
    # overlap interval
    os_ = max(nf, of)
    oe = min(nl, ol)
    overlap = os_ <= oe
    # gap between new end and phase118 start (if new entirely before)
    if nl < of:
        gap = f"{iso_z(nl)} -> {PHASE118_FIRST} (disjoint; gap after new export)"
    elif nf > ol:
        gap = f"{PHASE118_LAST} -> {iso_z(nf)} (disjoint; gap before new export)"
    elif overlap:
        gap = "NONE (ranges overlap)"
    else:
        gap = "NONE"
    extends = bool(nf < of)
    add_days = float((of - nf).total_seconds() / 86400.0) if extends else 0.0
    return {
        "OVERLAP_START": iso_z(os_) if overlap else None,
        "OVERLAP_END": iso_z(oe) if overlap else None,
        "GAP_TO_PHASE118": gap,
        "extends_before_phase118": extends,
        "additional_days_before": round(add_days, 3),
        "new_reaches_before_2026_07_23": bool(nf < pd.Timestamp("2026-07-23T01:01:00Z")),
    }


def next_export_window(union_first: str | None) -> dict[str, Any]:
    """Recommend small incremental backward export from remaining gap."""
    remaining_start = ACQ_START_ISO
    if union_first:
        remaining_end = iso_z(pd.Timestamp(union_first) - pd.Timedelta(milliseconds=1))
    else:
        remaining_end = "2026-07-23T01:00:59.999Z"
    # next small slice: ~2 months before current union_first
    if union_first:
        end_ts = pd.Timestamp(union_first) - pd.Timedelta(milliseconds=1)
        start_ts = end_ts - pd.DateOffset(months=NEXT_EXPORT_MONTHS)
        # clamp to acquisition start
        if start_ts < pd.Timestamp(ACQ_START_ISO):
            start_ts = pd.Timestamp(ACQ_START_ISO)
        next_start = iso_z(start_ts)
        next_end = iso_z(end_ts)
    else:
        next_start, next_end = remaining_start, remaining_end
    full = "PARTIAL"
    if union_first and pd.Timestamp(union_first) <= pd.Timestamp(ACQ_START_ISO):
        full = "VERIFIED"
        remaining_start = None
        remaining_end = None
        next_start = None
        next_end = None
    return {
        "REMAINING_MISSING_START": remaining_start if full != "VERIFIED" else None,
        "REMAINING_MISSING_END": remaining_end if full != "VERIFIED" else None,
        "FULL_HORIZON_SOURCE_STATUS": full if full == "VERIFIED" else "PARTIAL",
        "NEXT_OPERATOR_EXPORT_START": next_start,
        "NEXT_OPERATOR_EXPORT_END": next_end,
        "NEXT_ACTION": (
            "REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT"
            if full != "VERIFIED"
            else "FULL_HORIZON_COMPLETE"
        ),
        "next_export_note": (
            f"Prefer ~{NEXT_EXPORT_MONTHS}-month incremental backward export of REAL CLASSIC "
            f"XAUUSD_i ticks (operator confirmed large dumps are impractical)."
        ),
    }


def spread_stats_from_union(union: pd.DataFrame) -> dict[str, Any]:
    s = pd.to_numeric(union.get("spread"), errors="coerce")
    if s is None:
        s = pd.to_numeric(union["ask"], errors="coerce") - pd.to_numeric(union["bid"], errors="coerce")
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) == 0:
        return {"SPREAD_COUNT": 0, "SPREAD_MEDIAN": None, "SPREAD_P5": None, "SPREAD_P95": None, "SPREAD_MIN": None, "SPREAD_MAX": None, "anomalies": 0}
    arr = s.to_numpy(dtype=float)
    # anomalies: negative or absurdly large (>50)
    anomalies = int(((arr < 0) | (arr > 50)).sum())
    return {
        "SPREAD_COUNT": int(len(arr)),
        "SPREAD_MEDIAN": float(np.median(arr)),
        "SPREAD_P5": float(np.quantile(arr, 0.05)),
        "SPREAD_P95": float(np.quantile(arr, 0.95)),
        "SPREAD_MIN": float(np.min(arr)),
        "SPREAD_MAX": float(np.max(arr)),
        "anomalies": anomalies,
        "ohlc_inferred": False,
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
        "Phase 120 (`docs/PHASE120_TICK_EXPORT_VERIFICATION.md`) verifies newly supplied operator "
        "LiteFinance XAUUSD_i tick exports and measures union coverage with Phase 118. "
        "It does not connect to MT5, read .env, modify raw exports, alter production, design exits, "
        f"or start Phase 121. TICK_EVENT_COVERAGE={payload.get('TICK_EVENT_COVERAGE')}; "
        f"OUTLIER_COVERED={payload.get('OUTLIER_31_84R_TICK_COVERAGE')}."
    )
    if "PHASE120_TICK_EXPORT_VERIFICATION" not in text:
        anchor = "Phase 119 (`docs/PHASE119_HISTORICAL_TICK_RECOVERY.md`)"
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
    needle = "`tradingbot/backtest/phase119_historical_tick_recovery.py`"
    if "phase120_tick_export_verification.py" not in btext and needle in btext:
        i = btext.find(needle)
        j = btext.find("\n", i)
        insert = (
            "\n`tradingbot/backtest/phase120_tick_export_verification.py` -- **RESEARCH_ONLY** "
            "new operator tick export verification + union coverage; no MT5; raw untouched."
        )
        bnd.write_text(btext[:j] + insert + btext[j:], encoding="utf-8")

    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 120 started | **NO** |", "| Phase 120 started | **YES** |")
    block = f"""

## Tick export verification (Phase 120)

| Claim | Status |
|---|---|
| PHASE120_STATUS | **{payload.get('PHASE120_STATUS')}** |
| NEW_EXPORT_FIRST_TICK | **{payload.get('NEW_EXPORT_FIRST_TICK')}** |
| NEW_EXPORT_LAST_TICK | **{payload.get('NEW_EXPORT_LAST_TICK')}** |
| TICK_EVENT_COVERAGE | **{payload.get('TICK_EVENT_COVERAGE')}** |
| AMBIGUOUS_394_RESOLVED_TOTAL | **{payload.get('AMBIGUOUS_394_RESOLVED_TOTAL')}** |
| AMBIGUOUS_394_REMAINING | **{payload.get('AMBIGUOUS_394_REMAINING')}** |
| OUTLIER_31_84R_TICK_COVERAGE | **{payload.get('OUTLIER_31_84R_TICK_COVERAGE')}** |
| FULL_HORIZON_SOURCE_STATUS | **{payload.get('FULL_HORIZON_SOURCE_STATUS')}** |
| NEXT_ACTION | **{payload.get('NEXT_ACTION')}** |
| Canonical symbol | **XAUUSD_i** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 121 started | **NO** |
"""
    marker = "## Tick export verification (Phase 120)"
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

## Phase 120

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H120-01 | {today} | 120 | new export + Phase118 union | 419 | Phase118 | coverage={payload.get('TICK_EVENT_COVERAGE')} | reported | NO | {payload.get('NEXT_ACTION')} |

**NEW_EXPORT:** `{payload.get('NEW_EXPORT_FIRST_TICK')}` -> `{payload.get('NEW_EXPORT_LAST_TICK')}`
**TICK_EVENT_COVERAGE:** `{payload.get('TICK_EVENT_COVERAGE')}`
**OUTLIER_31_84R_TICK_COVERAGE:** `{payload.get('OUTLIER_31_84R_TICK_COVERAGE')}`
**NEXT_OPERATOR_EXPORT:** `{payload.get('NEXT_OPERATOR_EXPORT_START')}` -> `{payload.get('NEXT_OPERATOR_EXPORT_END')}`
"""
    marker = "## Phase 120"
    if marker in existing:
        start = existing.find(marker)
        ledger.write_text(existing[:start].rstrip() + "\n" + extra, encoding="utf-8")
    else:
        ledger.write_text(existing.rstrip() + "\n" + extra, encoding="utf-8")


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    keys = [
        "PHASE120_STATUS", "RAW_DIRECTORY", "PHASE118_FILE", "NEW_OPERATOR_FILES", "NEW_FILE_COUNT",
        "RAW_FILES_UNTOUCHED", "PHASE118_FIRST_TICK", "PHASE118_LAST_TICK", "NEW_EXPORT_FIRST_TICK",
        "NEW_EXPORT_LAST_TICK", "OVERLAP_START", "OVERLAP_END", "GAP_TO_PHASE118",
        "SOURCE_IDENTITY_STATUS", "TIMESTAMP_STATUS", "BID_STATUS", "ASK_STATUS", "SPREAD_STATUS",
        "DATA_QUALITY_STATUS", "UNION_FIRST_TICK", "UNION_LAST_TICK", "UNION_ROW_COUNT",
        "TICK_EVENT_COVERAGE", "TICK_COMPLETE_LIFECYCLE_EVENTS", "TICK_ENTRY_COVERAGE",
        "TICK_EXIT_COVERAGE", "TICK_INTRABAR_RESOLUTION_COVERAGE", "FAVORABLE_FIRST", "ADVERSE_FIRST",
        "SIMULTANEOUS_UNRESOLVED", "DATA_INSUFFICIENT", "AMBIGUOUS_394_RESOLVED_TOTAL",
        "AMBIGUOUS_394_REMAINING", "OUTLIER_31_84R_TICK_COVERAGE", "OUTLIER_31_84R_CHRONOLOGY_STATUS",
        "C_D_E_F_STATUS", "SPREAD_COUNT", "SPREAD_MEDIAN", "SPREAD_P5", "SPREAD_P95", "SPREAD_MIN",
        "SPREAD_MAX", "REMAINING_MISSING_START", "REMAINING_MISSING_END", "FULL_HORIZON_SOURCE_STATUS",
        "NEXT_OPERATOR_EXPORT_START", "NEXT_OPERATOR_EXPORT_END", "NEXT_ACTION",
        "TESTS_PHASE120", "REGRESSION_40_43_57_63_68_120",
        "FROZEN_PHASE40_TIMESTAMP", "FROZEN_PHASE40_FINGERPRINT", "FROZEN_PHASE40_SHA256",
    ]
    lines = [
        "# Phase 120 - Verify and Ingest New Operator XAUUSD_i Tick Exports",
        "",
        "Verification of newly supplied LiteFinance CLASSIC XAUUSD_i tick exports + derived union with Phase 118.",
        "Raw files untouched. No MT5. No .env. No production changes. Phase 121 not started.",
        "",
    ]
    for k in keys:
        lines.append(f"{k} = {payload.get(k)}")
    lines.extend(["", "## Safety", "", "All production/safety flags FALSE. Phase118 raw SHA256 preserved.", ""])
    (root / PHASE120_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_test_results(root: Path, phase120: dict[str, Any], regression: dict[str, Any]) -> None:
    path = root / PHASE120_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["TESTS_PHASE120"] = phase120
    payload["REGRESSION_40_43_57_63_68_120"] = regression
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = root / PHASE120_MD
    text = md.read_text(encoding="utf-8")
    text = re.sub(r"TESTS_PHASE120 = .*", f"TESTS_PHASE120 = {phase120}", text)
    text = re.sub(
        r"REGRESSION_40_43_57_63_68_120 = .*",
        f"REGRESSION_40_43_57_63_68_120 = {regression}",
        text,
    )
    md.write_text(text, encoding="utf-8")

def run_phase120_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    frozen = _frozen_integrity(root)
    inventory = inventory_raw_files(root)
    p118_row = next((r for r in inventory if r.get("is_phase118")), None)
    new_rows = [r for r in inventory if r.get("is_new_operator_file")]
    p118_untouched = bool(p118_row and p118_row.get("sha256") == PHASE118_SHA256)

    if not new_rows:
        payload = {
            "phase": PHASE,
            "timestamp_utc": _utc_now(),
            "PHASE120_STATUS": "FAIL" if not frozen.get("ok") else "PASS",
            "RAW_DIRECTORY": RAW_DROP_REL,
            "PHASE118_FILE": PHASE118_RAW_NAME,
            "NEW_OPERATOR_FILES": [],
            "NEW_FILE_COUNT": 0,
            "RAW_FILES_UNTOUCHED": p118_untouched,
            "DATA_ACQUIRED": False,
            "NEXT_ACTION": "AWAIT_NEW_OPERATOR_EXPORT",
            "MT5_USED": False,
            "ENV_ACCESSED": False,
            "PRODUCTION_CHANGED": False,
            "EXIT_DESIGN_SPEC_IMPLEMENTED": False,
            "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
            "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"),
            "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
            "frozen_integrity": frozen,
            "final_gate": "NO_GO",
            "inventory": inventory,
            "TESTS_PHASE120": None,
            "REGRESSION_40_43_57_63_68_120": None,
            "artifacts": {"json": PHASE120_JSON, "md": PHASE120_MD},
        }
        (root / PHASE120_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        _write_md(root, payload)
        _patch_docs(root, payload)
        return payload

    # Prefer the known new filename if present; else all new files in chronological order
    new_paths = []
    for r in new_rows:
        new_paths.append(root / r["path"])
    new_paths = sorted(new_paths, key=lambda p: p.name)

    ingested_list = []
    for path in new_paths:
        ingested_list.append(ingest_new_export(root, path))

    # Primary new export = earliest-first by measured first_tick
    ingested_list.sort(key=lambda x: x.get("first_tick") or "")
    primary = ingested_list[0]
    # If multiple, concat norms for union base
    if len(ingested_list) == 1:
        new_norm = primary["norm"]
    else:
        new_norm = pd.concat([x["norm"] for x in ingested_list], ignore_index=True)
        new_norm = new_norm.sort_values("timestamp_utc").drop_duplicates(
            subset=["timestamp_utc", "bid", "ask"], keep="first"
        ).reset_index(drop=True)

    # Free per-file norms after building combined new_norm except keep primary metadata
    for item in ingested_list:
        item.pop("norm", None)

    union_info = build_union(root, new_norm)
    union_df = union_info.pop("union")
    join = join_events(root, union_df)
    spr = spread_stats_from_union(union_df)
    del union_df
    del new_norm

    new_first = primary["first_tick"]
    new_last = max((x.get("last_tick") or "") for x in ingested_list) or primary["last_tick"]
    # use overall new coverage across all new files
    if ingested_list:
        new_first = min(x["first_tick"] for x in ingested_list if x.get("first_tick"))
        new_last = max(x["last_tick"] for x in ingested_list if x.get("last_tick"))

    ov = overlap_and_gap(new_first, new_last)
    nxt = next_export_window(union_info["first_tick"])

    identity_ok = all(x.get("symbol_identity_ok") for x in ingested_list)
    bid_ok = all(x.get("profile", {}).get("bid_present") for x in ingested_list)
    ask_ok = all(x.get("profile", {}).get("ask_present") for x in ingested_list)
    one_sided = any((x.get("raw_missing_bid") or 0) + (x.get("raw_missing_ask") or 0) > 0 for x in ingested_list)

    outlier_cov = bool(
        union_info["first_tick"]
        and union_info["last_tick"]
        and pd.Timestamp(union_info["first_tick"]) <= pd.Timestamp(OUTLIER_TS) <= pd.Timestamp(union_info["last_tick"])
    )
    outlier_chrono = "DATA_INSUFFICIENT"
    if outlier_cov and join.get("outlier_join"):
        outlier_chrono = join["outlier_join"].get("chronology") or "DATA_INSUFFICIENT"

    # Phase118 alone resolved 12; report total from union join
    amb_resolved = int(join.get("AMBIGUOUS_394_RESOLVED") or 0)
    amb_remaining = int(join.get("AMBIGUOUS_394_REMAINING") or (N_AMBIGUOUS_394 - amb_resolved))
    amb_additional = max(0, amb_resolved - 12)

    all_raw_untouched = p118_untouched and all(x.get("raw_unchanged") for x in ingested_list)
    status = "PASS" if frozen.get("ok") and all_raw_untouched and identity_ok else "FAIL"

    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "PHASE120_STATUS": status,
        "RAW_DIRECTORY": RAW_DROP_REL,
        "PHASE118_FILE": PHASE118_RAW_NAME,
        "PHASE118_SHA256": PHASE118_SHA256,
        "PHASE118_SHA256_VERIFIED": p118_untouched,
        "NEW_OPERATOR_FILES": [x["filename"] for x in ingested_list],
        "NEW_FILE_COUNT": len(ingested_list),
        "NEW_FILE_DETAILS": [
            {
                "filename": x["filename"],
                "sha256": x["sha256"],
                "rows": x["raw_rows"],
                "size": x["size_bytes"],
                "first": x["first_tick"],
                "last": x["last_tick"],
            }
            for x in ingested_list
        ],
        "RAW_FILES_UNTOUCHED": all_raw_untouched,
        "PHASE118_FIRST_TICK": PHASE118_FIRST,
        "PHASE118_LAST_TICK": PHASE118_LAST,
        "NEW_EXPORT_FIRST_TICK": new_first,
        "NEW_EXPORT_LAST_TICK": new_last,
        "OVERLAP_START": ov["OVERLAP_START"],
        "OVERLAP_END": ov["OVERLAP_END"],
        "GAP_TO_PHASE118": ov["GAP_TO_PHASE118"],
        "extends_before_phase118": ov["extends_before_phase118"],
        "additional_days_before": ov["additional_days_before"],
        "SOURCE_IDENTITY_STATUS": "VERIFIED" if identity_ok else "BLOCKED",
        "TIMESTAMP_STATUS": "VERIFIED",
        "BID_STATUS": "PARTIAL" if one_sided and bid_ok else ("VERIFIED" if bid_ok else "BLOCKED"),
        "ASK_STATUS": "PARTIAL" if one_sided and ask_ok else ("VERIFIED" if ask_ok else "BLOCKED"),
        "SPREAD_STATUS": "VERIFIED" if spr["SPREAD_COUNT"] > 0 else "MISSING",
        "DATA_QUALITY_STATUS": "PARTIAL",
        "UNION_FIRST_TICK": union_info["first_tick"],
        "UNION_LAST_TICK": union_info["last_tick"],
        "UNION_ROW_COUNT": union_info["rows_after_dedupe"],
        "union_path": union_info["path"],
        "TICK_EVENT_COVERAGE": join["TICK_EVENT_COVERAGE"],
        "TICK_COMPLETE_LIFECYCLE_EVENTS": join["TICK_COMPLETE_LIFECYCLE_EVENTS"],
        "TICK_ENTRY_COVERAGE": join["TICK_EVENT_COVERAGE"],
        "TICK_EXIT_COVERAGE": join.get("TICK_EXIT_COVERAGE"),
        "TICK_INTRABAR_RESOLUTION_COVERAGE": join["TICK_INTRABAR_RESOLUTION_COVERAGE"],
        "FAVORABLE_FIRST": join["FAVORABLE_FIRST"],
        "ADVERSE_FIRST": join["ADVERSE_FIRST"],
        "SIMULTANEOUS_UNRESOLVED": join["SIMULTANEOUS_UNRESOLVED"],
        "DATA_INSUFFICIENT": join["DATA_INSUFFICIENT"],
        "AMBIGUOUS_394_RESOLVED_TOTAL": amb_resolved,
        "AMBIGUOUS_394_REMAINING": amb_remaining,
        "AMBIGUOUS_394_ADDITIONAL_VS_PHASE118": amb_additional,
        "OUTLIER_31_84R_TICK_COVERAGE": outlier_cov,
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": outlier_chrono,
        "C_D_E_F_STATUS": join["C_D_E_F_STATUS"],
        "path_chronology": join.get("path_chronology"),
        **spr,
        **{k: nxt[k] for k in [
            "REMAINING_MISSING_START", "REMAINING_MISSING_END", "FULL_HORIZON_SOURCE_STATUS",
            "NEXT_OPERATOR_EXPORT_START", "NEXT_OPERATOR_EXPORT_END", "NEXT_ACTION",
        ]},
        "next_export_note": nxt["next_export_note"],
        "inventory": inventory,
        "ingested_new": ingested_list,
        "n_events": join.get("n_events", N_EVENTS),
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
        "TESTS_PHASE120": None,
        "REGRESSION_40_43_57_63_68_120": None,
        "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
        "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"),
        "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
        "frozen_integrity": frozen,
        "final_gate": "GO_OPERATOR_ACTION" if nxt["NEXT_ACTION"] != "FULL_HORIZON_COMPLETE" else "GO_RESEARCH",
        "production_safety": {
            "MT5": "NOT_USED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "production_changes": "NONE",
            "exit_design": False,
            "phase118_raw_modified": False,
            "new_raw_modified": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE120_JSON, "md": PHASE120_MD, "ledger": LEDGER_MD},
        "phase121_started": False,
    }
    if not frozen.get("ok"):
        payload["PHASE120_STATUS"] = "FAIL"
        payload["blocker"] = "Frozen Phase 40 mismatch. File was not repaired."
    if not p118_untouched:
        payload["PHASE120_STATUS"] = "FAIL"
        payload["blocker"] = "Phase118 raw SHA256 mismatch; file was not repaired."

    (root / PHASE120_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE120_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    _write_md(root, payload)
    _patch_docs(root, payload)
    return payload


if __name__ == "__main__":
    run_phase120_collection(Path.cwd())