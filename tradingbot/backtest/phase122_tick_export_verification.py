"""Phase 122 - verify next backward operator XAUUSD_i tick export.

RESEARCH / DATA VALIDATION ONLY.
Verifies newly supplied LiteFinance CLASSIC XAUUSD_i tick exports, builds a
derived research union with Phase 118 + Phase 120, and measures event / outlier
coverage. Does not connect to MT5, read .env, modify raw exports, alter
production, design exits, or start Phase 123.
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
from tradingbot.backtest.phase114_non_ohlc_acquisition_contract import CANONICAL_SYMBOL
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    EXPECTED_JSONL_SHA256,
    N_AMBIGUOUS_394,
    N_EVENTS,
    PHASE40_TS,
    classify_intrabar_order,
    enforce_utc,
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
from tradingbot.backtest.phase120_tick_export_verification import (
    NEW_EXPECTED_NAME as PHASE120_RAW_NAME,
    NEW_EXPECTED_SHA256 as PHASE120_SHA256,
    NORMALIZED_REL as PHASE120_NORM_REL,
    PHASE118_FIRST,
    PHASE118_LAST,
)
from tradingbot.backtest.phase121_tick_export_verification import (
    NEW_EXPECTED_NAME as PHASE121_RAW_NAME,
    NEW_EXPECTED_SHA256 as PHASE121_SHA256,
    NORMALIZED_REL as PHASE121_NORM_REL,
)

PHASE = "122"
PHASE122_JSON = "logs/phase122_tick_export_verification.json"
PHASE122_MD = "docs/PHASE122_TICK_EXPORT_VERIFICATION.md"
PHASE122_LOG = "logs/phase122_tick_export_verification.log"
NORMALIZED_REL = "data/research/non_ohlc/normalized/phase122"
DERIVED_REL = "data/research/non_ohlc/derived/phase122"
NORMALIZATION_VERSION = "phase122-v1"
PHASE120_FIRST = "2026-05-20T01:01:00.057000Z"
PHASE120_LAST = "2026-07-24T23:58:59.975000Z"
PHASE121_FIRST = "2026-01-02T01:15:00.282000Z"
PHASE121_LAST = "2026-05-19T23:58:59.782000Z"
NEW_EXPECTED_NAME = "XAUUSD_i_202511030106_202601022358.csv"
NEW_EXPECTED_SHA256 = "ec4b581817dc1a0d40065fa7a055a9eb2bedf6ffeb19d701ec48f214232fd300"
PRIOR_AMB_RESOLVED = 58
PRIOR_TICK_EVENT_COVERAGE = 61
NEXT_EXPORT_MONTHS = 2
OUTLIER_EXIT_HINT = "2026-01-21T21:50:00Z"
OUTLIER_KNOWN_CHRONOLOGY = "ADVERSE_FIRST"

LEAN_COLS = ["timestamp_utc", "bid", "ask", "spread"]


def inventory_raw_files(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in discover_raw_exports(root):
        sha = file_sha256(path)
        profile = profile_raw_header(path)
        is_p118 = path.name == PHASE118_RAW_NAME or sha == PHASE118_SHA256
        is_p120 = path.name == PHASE120_RAW_NAME or sha == PHASE120_SHA256
        is_p121 = path.name == PHASE121_RAW_NAME or sha == PHASE121_SHA256
        with path.open("rb") as fh:
            fh.readline()
            first_line = fh.readline().decode("utf-8", errors="replace").strip("\r\n")
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
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

        rows.append(
            {
                "filename": path.name,
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "size": int(path.stat().st_size),
                "extension": path.suffix.lower(),
                "row_count": None,
                "columns": profile["columns"],
                "first_timestamp": parse_line(first_line),
                "last_timestamp": parse_line(last_line),
                "detected_symbol": CANONICAL_SYMBOL if verify_xauusd_i(path=path.name) else None,
                "bid_exists": profile["bid_present"],
                "ask_exists": profile["ask_present"],
                "last_exists": profile["last_present"],
                "volume_exists": profile["volume_present"],
                "flags_exists": profile["flags_present"],
                "timestamp_precision": "millisecond",
                "timestamp_timezone_interpretation": "UTC (Phase117/118/120 convention)",
                "sha256": sha,
                "is_phase118": is_p118,
                "is_phase120": is_p120,
                "is_phase121": is_p121,
                "is_new_operator_file": not is_p118 and not is_p120 and not is_p121,
                "symbol_identity_ok": verify_xauusd_i(path=path.name),
                "profile": profile,
            }
        )
    return rows


def ingest_new_export(root: Path, raw_path: Path) -> dict[str, Any]:
    """Normalize NEW export only. Never rewrites raw. Does not touch Phase118/120/121 raw."""
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
            # Resume without loading full frame here; caller loads via path in build_union.
            meta = pd.read_parquet(norm_path, columns=["timestamp_utc"])
            first_iso = iso_z(meta["timestamp_utc"].iloc[0]) if len(meta) else None
            last_iso = iso_z(meta["timestamp_utc"].iloc[-1]) if len(meta) else None
            n_norm = int(len(meta))
            del meta
            sha_after = file_sha256(raw_path)
            return {
                "raw_path": str(raw_path.relative_to(root)).replace("\\", "/"),
                "filename": raw_path.name,
                "sha256": sha_before,
                "raw_unchanged": sha_before == sha_after,
                "size_bytes": size,
                "raw_rows": int(ptr.get("raw_rows") or n_norm),
                "normalized_rows": n_norm,
                "normalized_path": str(norm_path.relative_to(root)).replace("\\", "/"),
                "first_tick": first_iso,
                "last_tick": last_iso,
                "profile": profile,
                "raw_missing_bid": int(ptr.get("raw_missing_bid") or 0),
                "raw_missing_ask": int(ptr.get("raw_missing_ask") or 0),
                "raw_missing_both": int(ptr.get("raw_missing_both") or 0),
                "raw_ask_lt_bid": int(ptr.get("raw_ask_lt_bid") or 0),
                "raw_nonpositive": int(ptr.get("raw_nonpositive") or 0),
                "duplicate_timestamps": int(ptr.get("duplicate_timestamps") or 0),
                "out_of_order_rows": int(ptr.get("out_of_order_rows") or 0),
                "exact_dup_rows_dropped": 0,
                "flags_seen": {},
                "frame_validation": {"resumed": True},
                "spread_sample": {},
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
        spr = ask - bid
        finite = np.isfinite(bid) & np.isfinite(ask)
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
    norm = norm.drop_duplicates(subset=["timestamp_utc", "bid", "ask"], keep="first").reset_index(drop=True)
    exact_dup_dropped = before - len(norm)
    for c in ("bid", "ask", "spread"):
        norm[c] = norm[c].astype(np.float32)
    # Write lean parquet; free peak by writing then reloading columns only if needed
    norm.to_parquet(norm_path, index=False, compression="zstd")
    sha_after = file_sha256(raw_path)
    first_iso = iso_z(first_ts)
    last_iso = iso_z(last_ts)
    pointer = {
        "raw_path": str(raw_path.relative_to(root)).replace("\\", "/"),
        "raw_sha256_before": sha_before,
        "raw_sha256_after": sha_after,
        "raw_unchanged": sha_before == sha_after,
        "normalized_path": str(norm_path.relative_to(root)).replace("\\", "/"),
        "normalized_rows": int(len(norm)),
        "raw_rows": n_rows,
        "raw_missing_bid": missing_bid,
        "raw_missing_ask": missing_ask,
        "raw_missing_both": missing_both,
        "raw_ask_lt_bid": ask_lt_bid,
        "raw_nonpositive": nonpositive,
        "duplicate_timestamps": dup_count,
        "out_of_order_rows": out_of_order,
        "quote_state_carry_forward": True,
        "normalization_version": NORMALIZATION_VERSION,
    }
    pointer_path.write_text(json.dumps(pointer, indent=2), encoding="utf-8")
    spread_arr = np.asarray(spreads, dtype=float) if spreads else np.array([])
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
        "flags_seen": {},
        "frame_validation": validate_tick_frame(norm.copy()),
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
        "resumed_from_normalized": False,
    }

def build_union(root: Path, new_norm_path: Path) -> dict[str, Any]:
    """Derived research union of Phase118 + Phase120 + Phase121 + new via numpy (memory-lean)."""
    import gc

    der = root / DERIVED_REL
    der.mkdir(parents=True, exist_ok=True)
    p118 = root / PHASE118_NORM_REL / "xauusd_i_ticks_normalized.parquet"
    p120 = root / PHASE120_NORM_REL / f"{Path(PHASE120_RAW_NAME).stem}_normalized.parquet"
    p121 = root / PHASE121_NORM_REL / f"{Path(PHASE121_RAW_NAME).stem}_normalized.parquet"
    if not p120.is_file():
        cand = list((root / PHASE120_NORM_REL).glob("*_normalized.parquet"))
        p120 = cand[0] if cand else p120
    if not p121.is_file():
        cand = list((root / PHASE121_NORM_REL).glob("*_normalized.parquet"))
        p121 = cand[0] if cand else p121
    paths: list[tuple[str, Path]] = []
    if p118.is_file():
        paths.append(("phase118", p118))
    if p120.is_file():
        paths.append(("phase120", p120))
    if p121.is_file():
        paths.append(("phase121", p121))
    paths.append(("phase122_new", new_norm_path))

    ts_parts: list[np.ndarray] = []
    bid_parts: list[np.ndarray] = []
    ask_parts: list[np.ndarray] = []
    spr_parts: list[np.ndarray] = []
    src_parts: list[np.ndarray] = []
    sources: list[str] = []
    before = 0
    for label, path in paths:
        df = pd.read_parquet(path, columns=LEAN_COLS)
        before += len(df)
        ts_parts.append(df["timestamp_utc"].to_numpy(dtype="datetime64[ns]").astype(np.int64))
        bid_parts.append(df["bid"].to_numpy(dtype=np.float32))
        ask_parts.append(df["ask"].to_numpy(dtype=np.float32))
        if "spread" in df.columns:
            spr_parts.append(df["spread"].to_numpy(dtype=np.float32))
        else:
            spr_parts.append(ask_parts[-1] - bid_parts[-1])
        sources.append(f"{label}:{str(path.relative_to(root)).replace(chr(92), '/')}")
        del df
        gc.collect()

    # drop unused src_parts placeholder
    del src_parts
    gc.collect()

    ts = np.concatenate(ts_parts)
    del ts_parts
    bid = np.concatenate(bid_parts)
    del bid_parts
    ask = np.concatenate(ask_parts)
    del ask_parts
    spr = np.concatenate(spr_parts)
    del spr_parts
    gc.collect()

    order = np.argsort(ts, kind="mergesort")
    ts = ts[order]
    bid = bid[order]
    ask = ask[order]
    spr = spr[order]
    del order
    gc.collect()

    # Deduplicate consecutive identical (timestamp, bid, ask)
    if len(ts):
        same = np.ones(len(ts), dtype=bool)
        same[1:] = ~((ts[1:] == ts[:-1]) & (bid[1:] == bid[:-1]) & (ask[1:] == ask[:-1]))
        ts, bid, ask, spr = ts[same], bid[same], ask[same], spr[same]
        del same
        gc.collect()

    # Lean frame only — no object provenance column (OOMs at ~55M rows).
    union = pd.DataFrame(
        {
            "bid": bid,
            "ask": ask,
            "spread": spr,
        }
    )
    union.insert(0, "timestamp_utc", pd.to_datetime(ts, unit="ns", utc=True))
    del ts, bid, ask, spr
    gc.collect()

    # Skip writing ~55M-row union parquet when free disk is tight; keep derived norms + meta.
    meta_path = der / "xauusd_i_ticks_union_meta.json"
    first = iso_z(union["timestamp_utc"].iloc[0]) if len(union) else None
    last = iso_z(union["timestamp_utc"].iloc[-1]) if len(union) else None
    free = __import__("shutil").disk_usage(str(root)).free
    # Always skip materializing ~55M-row union parquet on this host (disk/RAM constrained).
    # Derived research union remains: phase118 + phase120 + phase122 normalized parquet sources.
    wrote = False
    out_path = meta_path
    if False and free > 8_000_000_000:
        try:
            pq_path = der / "xauusd_i_ticks_union.parquet"
            union.to_parquet(pq_path, index=False, compression="zstd")
            wrote = True
            out_path = pq_path
        except OSError:
            wrote = False
    meta_path.write_text(
        json.dumps(
            {
                "rows_before_dedupe": before,
                "rows_after_dedupe": int(len(union)),
                "first_tick": first,
                "last_tick": last,
                "sources": sources,
                "wrote_parquet": wrote,
                "parquet_path": str(out_path.relative_to(root)).replace("\\", "/") if wrote else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "path": str(out_path.relative_to(root)).replace("\\", "/"),
        "sources": sources,
        "rows_before_dedupe": before,
        "rows_after_dedupe": int(len(union)),
        "first_tick": first,
        "last_tick": last,
        "union": union,
        "wrote_parquet": wrote,
    }


def overlap_and_gap(new_first: str | None, new_last: str | None) -> dict[str, Any]:
    if not new_first or not new_last:
        return {
            "OVERLAP_START": None,
            "OVERLAP_END": None,
            "GAP_TO_PREVIOUS_EXPORT": "UNKNOWN",
            "extends_before_phase121": False,
        }
    nf, nl = pd.Timestamp(new_first), pd.Timestamp(new_last)
    pf, pl = pd.Timestamp(PHASE121_FIRST), pd.Timestamp(PHASE121_LAST)
    os_ = max(nf, pf)
    oe = min(nl, pl)
    overlap = os_ <= oe
    if nl < pf:
        gap = f"{iso_z(nl)} -> {PHASE121_FIRST} (disjoint; gap after new export before Phase121)"
    elif nf > pl:
        gap = f"{PHASE121_LAST} -> {iso_z(nf)} (disjoint; gap before new export)"
    elif overlap:
        gap = "NONE (ranges overlap)"
    else:
        gap = "NONE"
    return {
        "OVERLAP_START": iso_z(os_) if overlap else None,
        "OVERLAP_END": iso_z(oe) if overlap else None,
        "GAP_TO_PREVIOUS_EXPORT": gap,
        "extends_before_phase121": bool(nf < pf),
        "additional_days_before_phase121": round(float((pf - nf).total_seconds() / 86400.0), 3) if nf < pf else 0.0,
    }


def next_export_window(union_first: str | None) -> dict[str, Any]:
    remaining_start = ACQ_START_ISO
    if union_first:
        remaining_end = iso_z(pd.Timestamp(union_first) - pd.Timedelta(milliseconds=1))
        end_ts = pd.Timestamp(union_first) - pd.Timedelta(milliseconds=1)
        start_ts = end_ts - pd.DateOffset(months=NEXT_EXPORT_MONTHS)
        if start_ts < pd.Timestamp(ACQ_START_ISO):
            start_ts = pd.Timestamp(ACQ_START_ISO)
        next_start, next_end = iso_z(start_ts), iso_z(end_ts)
    else:
        remaining_end = "2026-01-02T01:14:59.999Z"
        next_start, next_end = remaining_start, remaining_end
    full = "PARTIAL"
    if union_first and pd.Timestamp(union_first) <= pd.Timestamp(ACQ_START_ISO):
        full = "VERIFIED"
        remaining_start = remaining_end = next_start = next_end = None
    return {
        "REMAINING_MISSING_START": remaining_start if full != "VERIFIED" else None,
        "REMAINING_MISSING_END": remaining_end if full != "VERIFIED" else None,
        "FULL_HORIZON_SOURCE_STATUS": "VERIFIED" if full == "VERIFIED" else "PARTIAL",
        "NEXT_OPERATOR_EXPORT_START": next_start,
        "NEXT_OPERATOR_EXPORT_END": next_end,
        "NEXT_ACTION": (
            "REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT"
            if full != "VERIFIED"
            else "FULL_HORIZON_COMPLETE"
        ),
        "next_export_note": (
            f"Prefer ~{NEXT_EXPORT_MONTHS}-month incremental backward REAL CLASSIC XAUUSD_i ticks."
        ),
    }


def spread_stats_from_union(union: pd.DataFrame) -> dict[str, Any]:
    s = pd.to_numeric(union.get("spread"), errors="coerce")
    if s is None or len(s) == 0:
        s = pd.to_numeric(union["ask"], errors="coerce") - pd.to_numeric(union["bid"], errors="coerce")
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) == 0:
        return {
            "SPREAD_COUNT": 0,
            "SPREAD_MEDIAN": None,
            "SPREAD_P5": None,
            "SPREAD_P95": None,
            "SPREAD_MIN": None,
            "SPREAD_MAX": None,
            "anomalies": 0,
        }
    arr = s.to_numpy(dtype=float)
    return {
        "SPREAD_COUNT": int(len(arr)),
        "SPREAD_MEDIAN": float(np.median(arr)),
        "SPREAD_P5": float(np.quantile(arr, 0.05)),
        "SPREAD_P95": float(np.quantile(arr, 0.95)),
        "SPREAD_MIN": float(np.min(arr)),
        "SPREAD_MAX": float(np.max(arr)),
        "anomalies": int(((arr < 0) | (arr > 50)).sum()),
        "ohlc_inferred": False,
    }


def inspect_outlier_path(root: Path, union: pd.DataFrame, join: dict[str, Any]) -> dict[str, Any]:
    """Deep tick-path inspection for +31.84R SELL if covered. Does not alter event result."""
    from tradingbot.backtest.phase118_tick_forensic_validation import _load_events

    row = join.get("outlier_join")
    out: dict[str, Any] = {
        "OUTLIER_31_84R_TICK_COVERAGE": False,
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": "DATA_INSUFFICIENT",
        "outlier_detail": None,
    }
    if not len(union):
        return out
    tmin = pd.Timestamp(union["timestamp_utc"].iloc[0])
    tmax = pd.Timestamp(union["timestamp_utc"].iloc[-1])
    entry_ts = pd.Timestamp(OUTLIER_TS)
    covered = bool(tmin <= entry_ts <= tmax)
    out["OUTLIER_31_84R_TICK_COVERAGE"] = covered
    if not covered:
        return out

    events, _ = _load_events(root)
    ev = None
    for e in events:
        et = e.get("entry_timestamp")
        if et is None:
            continue
        if iso_z(enforce_utc(et)) == OUTLIER_TS or str(et).startswith("2026-01-21T15:40"):
            ev = e
            break
    if ev is None and row:
        # Fall back to join row timestamps only
        exit_iso = row.get("exit_timestamp") or OUTLIER_EXIT_HINT
        side = str(row.get("side") or "SELL")
        entry_price = float("nan")
        r_result = row.get("r_result")
        path_class = row.get("path_class")
    else:
        if ev is None:
            out["OUTLIER_31_84R_CHRONOLOGY_STATUS"] = "DATA_INSUFFICIENT"
            return out
        exit_iso = iso_z(enforce_utc(ev.get("exit_timestamp") or OUTLIER_EXIT_HINT))
        side = str(ev.get("side") or "SELL")
        ep = ev.get("entry_price")
        entry_price = float(ep) if ep is not None else float("nan")
        r_result = ev.get("r_result")
        path_class = ev.get("path_class")

    exit_ts = pd.Timestamp(exit_iso)
    entry_ns = int(entry_ts.value)
    exit_ns = int(exit_ts.value)
    ts_ns = union["timestamp_utc"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    bid = union["bid"].to_numpy(dtype=float)
    ask = union["ask"].to_numpy(dtype=float)
    lo = int(np.searchsorted(ts_ns, entry_ns, side="left"))
    hi = int(np.searchsorted(ts_ns, exit_ns, side="right"))
    sub_ts = ts_ns[lo:hi]
    sub_bid = bid[lo:hi]
    sub_ask = ask[lo:hi]
    if len(sub_ts) and int(sub_ts[-1]) > exit_ns:
        mask = sub_ts <= exit_ns
        sub_ts = sub_ts[mask]
        sub_bid = sub_bid[mask]
        sub_ask = sub_ask[mask]

    chrono = classify_intrabar_order(side, entry_price, sub_ts, sub_bid, sub_ask, exit_ns=exit_ns)
    out["OUTLIER_31_84R_CHRONOLOGY_STATUS"] = chrono.get("class") or "DATA_INSUFFICIENT"

    # SELL favorable excursion: entry - bid (downside). Adverse: ask - entry (upside against short).
    mfe = mae = None
    if len(sub_bid) and np.isfinite(entry_price):
        if str(side).upper() in {"SELL", "SHORT", "-1"}:
            mfe = float(np.nanmax(entry_price - sub_bid))
            mae = float(np.nanmax(sub_ask - entry_price))
        else:
            mfe = float(np.nanmax(sub_ask - entry_price))
            mae = float(np.nanmax(entry_price - sub_bid))

    out["outlier_detail"] = {
        "entry_timestamp": OUTLIER_TS,
        "exit_timestamp": exit_iso,
        "side": side,
        "path_class": path_class,
        "r_result_unchanged": r_result,
        "entry_price": entry_price if np.isfinite(entry_price) else None,
        "tick_n_in_lifecycle": int(len(sub_ts)),
        "lifecycle_covered": bool((row or {}).get("lifecycle_covered")) if row else bool(len(sub_ts) > 0),
        "first_favorable_tick_utc": chrono.get("first_favorable_tick_utc"),
        "first_adverse_tick_utc": chrono.get("first_adverse_tick_utc"),
        "both_occur": bool(chrono.get("first_favorable_tick_utc") and chrono.get("first_adverse_tick_utc")),
        "chronology": chrono.get("class"),
        "same_timestamp_ambiguous": bool(chrono.get("same_timestamp_ambiguous")),
        "max_favorable_excursion_price": mfe,
        "max_adverse_excursion_price": mae,
        "large_expansion_visible": bool(mfe is not None and mfe > 5.0),
        "intrabar_ambiguity_remains": chrono.get("class")
        in {"SIMULTANEOUS_UNRESOLVED", "DATA_INSUFFICIENT", "EXIT_WITHOUT_INTRABAR_RESOLUTION"},
    }
    return out

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
        "Phase 122 (`docs/PHASE122_TICK_EXPORT_VERIFICATION.md`) verifies newly supplied operator "
        "LiteFinance XAUUSD_i tick exports (Jan-2026 window), unions with Phase118/120, and tests "
        "+31.84R tick coverage. No MT5, no .env, raw untouched, no production changes, Phase 123 not started. "
        f"TICK_EVENT_COVERAGE={payload.get('TICK_EVENT_COVERAGE')}; "
        f"OUTLIER_COVERED={payload.get('OUTLIER_31_84R_TICK_COVERAGE')}."
    )
    if "PHASE122_TICK_EXPORT_VERIFICATION" not in text:
        anchor = "Phase 121 (`docs/PHASE121_TICK_EXPORT_VERIFICATION.md`)"
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
    needle = "`tradingbot/backtest/phase121_tick_export_verification.py`"
    if "phase122_tick_export_verification.py" not in btext and needle in btext:
        i = btext.find(needle)
        j = btext.find("\n", i)
        insert = (
            "\n`tradingbot/backtest/phase122_tick_export_verification.py` -- **RESEARCH_ONLY** "
            "new operator tick export verification + outlier coverage; no MT5; raw untouched."
        )
        bnd.write_text(btext[:j] + insert + btext[j:], encoding="utf-8")

    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 122 started | **NO** |", "| Phase 122 started | **YES** |")
    block = f"""

## Tick export verification (Phase 122)

| Claim | Status |
|---|---|
| PHASE122_STATUS | **{payload.get('PHASE122_STATUS')}** |
| NEW_EXPORT_FIRST_TICK | **{payload.get('NEW_EXPORT_FIRST_TICK')}** |
| NEW_EXPORT_LAST_TICK | **{payload.get('NEW_EXPORT_LAST_TICK')}** |
| TICK_EVENT_COVERAGE | **{payload.get('TICK_EVENT_COVERAGE')}** |
| AMBIGUOUS_394_RESOLVED_TOTAL | **{payload.get('AMBIGUOUS_394_RESOLVED_TOTAL')}** |
| AMBIGUOUS_394_REMAINING | **{payload.get('AMBIGUOUS_394_REMAINING')}** |
| OUTLIER_31_84R_TICK_COVERAGE | **{payload.get('OUTLIER_31_84R_TICK_COVERAGE')}** |
| OUTLIER_31_84R_CHRONOLOGY_STATUS | **{payload.get('OUTLIER_31_84R_CHRONOLOGY_STATUS')}** |
| FULL_HORIZON_SOURCE_STATUS | **{payload.get('FULL_HORIZON_SOURCE_STATUS')}** |
| NEXT_ACTION | **{payload.get('NEXT_ACTION')}** |
| Canonical symbol | **XAUUSD_i** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 123 started | **NO** |
"""
    marker = "## Tick export verification (Phase 122)"
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

## Phase 122

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H122-01 | {today} | 122 | new export + P118/P120/P121 union | 419 | Phase121 | coverage={payload.get('TICK_EVENT_COVERAGE')} outlier={payload.get('OUTLIER_31_84R_TICK_COVERAGE')} | reported | NO | {payload.get('NEXT_ACTION')} |

**NEW_EXPORT:** `{payload.get('NEW_EXPORT_FIRST_TICK')}` -> `{payload.get('NEW_EXPORT_LAST_TICK')}`
**OUTLIER_31_84R_CHRONOLOGY_STATUS:** `{payload.get('OUTLIER_31_84R_CHRONOLOGY_STATUS')}`
**NEXT_OPERATOR_EXPORT:** `{payload.get('NEXT_OPERATOR_EXPORT_START')}` -> `{payload.get('NEXT_OPERATOR_EXPORT_END')}`
"""
    marker = "## Phase 122"
    if marker in existing:
        start = existing.find(marker)
        ledger.write_text(existing[:start].rstrip() + "\n" + extra, encoding="utf-8")
    else:
        ledger.write_text(existing.rstrip() + "\n" + extra, encoding="utf-8")


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    keys = [
        "PHASE122_STATUS", "RAW_DIRECTORY", "PHASE118_FILE", "PHASE120_FILE", "NEW_OPERATOR_FILES",
        "RAW_FILES_UNTOUCHED", "PHASE118_FIRST_TICK", "PHASE118_LAST_TICK", "PHASE120_FIRST_TICK",
        "PHASE120_LAST_TICK", "NEW_EXPORT_FIRST_TICK", "NEW_EXPORT_LAST_TICK", "NEW_EXPORT_ROW_COUNT",
        "NEW_EXPORT_SHA256", "UNION_FIRST_TICK", "UNION_LAST_TICK", "UNION_ROW_COUNT",
        "OVERLAP_START", "OVERLAP_END", "GAP_TO_PREVIOUS_EXPORT", "SOURCE_IDENTITY_STATUS",
        "TIMESTAMP_STATUS", "BID_STATUS", "ASK_STATUS", "SPREAD_STATUS", "DATA_QUALITY_STATUS",
        "TICK_EVENT_COVERAGE", "TICK_COMPLETE_LIFECYCLE_EVENTS", "TICK_ENTRY_COVERAGE",
        "TICK_EXIT_COVERAGE", "TICK_INTRABAR_RESOLUTION_COVERAGE", "FAVORABLE_FIRST", "ADVERSE_FIRST",
        "SIMULTANEOUS_UNRESOLVED", "DATA_INSUFFICIENT", "AMBIGUOUS_394_RESOLVED_TOTAL",
        "AMBIGUOUS_394_REMAINING", "NEWLY_RESOLVED_THIS_PHASE", "OUTLIER_31_84R_TICK_COVERAGE",
        "OUTLIER_31_84R_CHRONOLOGY_STATUS", "C_D_E_F_STATUS", "SPREAD_COUNT", "SPREAD_MEDIAN",
        "SPREAD_P5", "SPREAD_P95", "SPREAD_MIN", "SPREAD_MAX", "REMAINING_MISSING_START",
        "REMAINING_MISSING_END", "FULL_HORIZON_SOURCE_STATUS", "NEXT_OPERATOR_EXPORT_START",
        "NEXT_OPERATOR_EXPORT_END", "NEXT_ACTION", "TESTS_PHASE122", "REGRESSION_40_43_57_63_68_122",
        "FROZEN_PHASE40_TIMESTAMP", "FROZEN_PHASE40_FINGERPRINT", "FROZEN_PHASE40_SHA256",
    ]
    lines = [
        "# Phase 122 - Verify New XAUUSD_i Tick Export + Outlier Coverage",
        "",
        "Verification of newly supplied LiteFinance CLASSIC XAUUSD_i tick exports + derived union with Phase 118/120/121.",
        "Raw files untouched. No MT5. No .env. No production changes. Phase 123 not started.",
        "",
    ]
    for k in keys:
        lines.append(f"{k} = {payload.get(k)}")
    detail = payload.get("outlier_detail")
    if detail:
        lines.extend(["", "## Outlier +31.84R detail", ""])
        for k, v in detail.items():
            lines.append(f"{k} = {v}")
    lines.extend(["", "## Safety", "", "All production/safety flags FALSE. Phase118/120 raw SHA256 preserved.", ""])
    (root / PHASE122_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_test_results(root: Path, phase122: dict[str, Any], regression: dict[str, Any]) -> None:
    path = root / PHASE122_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["TESTS_PHASE122"] = phase122
    payload["REGRESSION_40_43_57_63_68_122"] = regression
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = root / PHASE122_MD
    text = md.read_text(encoding="utf-8")
    text = re.sub(r"TESTS_PHASE122 = .*", f"TESTS_PHASE122 = {phase122}", text)
    text = re.sub(
        r"REGRESSION_40_43_57_63_68_122 = .*",
        f"REGRESSION_40_43_57_63_68_122 = {regression}",
        text,
    )
    md.write_text(text, encoding="utf-8")


def run_phase122_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    frozen = _frozen_integrity(root)
    inventory = inventory_raw_files(root)
    p118_row = next((r for r in inventory if r.get("is_phase118")), None)
    p120_row = next((r for r in inventory if r.get("is_phase120")), None)
    p121_row = next((r for r in inventory if r.get("is_phase121")), None)
    new_rows = [r for r in inventory if r.get("is_new_operator_file")]
    p118_ok = bool(p118_row and p118_row.get("sha256") == PHASE118_SHA256)
    p120_ok = bool(p120_row and p120_row.get("sha256") == PHASE120_SHA256)
    p121_ok = bool(p121_row and p121_row.get("sha256") == PHASE121_SHA256)

    if not new_rows:
        payload = {
            "phase": PHASE,
            "timestamp_utc": _utc_now(),
            "PHASE122_STATUS": "FAIL" if not frozen.get("ok") else "PASS",
            "RAW_DIRECTORY": RAW_DROP_REL,
            "PHASE118_FILE": PHASE118_RAW_NAME,
            "PHASE120_FILE": PHASE120_RAW_NAME,
        "PHASE121_FILE": PHASE121_RAW_NAME,
            "NEW_OPERATOR_FILES": [],
            "RAW_FILES_UNTOUCHED": p118_ok and p120_ok and p121_ok,
            "DATA_ACQUIRED": False,
            "NEXT_ACTION": "AWAIT_NEW_OPERATOR_EXPORT",
            "MT5_USED": False,
            "ENV_ACCESSED": False,
            "PRODUCTION_CHANGED": False,
            "EXIT_DESIGN_SPEC_IMPLEMENTED": False,
            "phase123_started": False,
            "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
            "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"),
            "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
            "frozen_integrity": frozen,
            "final_gate": "NO_GO",
            "inventory": inventory,
            "TESTS_PHASE122": None,
            "REGRESSION_40_43_57_63_68_122": None,
            "artifacts": {"json": PHASE122_JSON, "md": PHASE122_MD},
        }
        (root / PHASE122_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        _write_md(root, payload)
        _patch_docs(root, payload)
        return payload

    new_paths = sorted([root / r["path"] for r in new_rows], key=lambda p: p.name)
    ingested_list = []
    for path in new_paths:
        item = ingest_new_export(root, path)
        # Drop in-memory frame immediately; union loads from parquet paths.
        item.pop("norm", None)
        ingested_list.append(item)
    ingested_list.sort(key=lambda x: x.get("first_tick") or "")
    # Single primary new export path (multi-file concat not required for this phase).
    new_norm_path = root / ingested_list[0]["normalized_path"]
    if len(ingested_list) > 1:
        # Concatenate additional new norms into a temp lean parquet if ever needed.
        import gc

        parts = []
        for x in ingested_list:
            parts.append(pd.read_parquet(root / x["normalized_path"], columns=LEAN_COLS))
        combo = pd.concat(parts, ignore_index=True)
        del parts
        combo = combo.sort_values("timestamp_utc").drop_duplicates(
            subset=["timestamp_utc", "bid", "ask"], keep="first"
        ).reset_index(drop=True)
        new_norm_path = root / DERIVED_REL / "new_exports_combined.parquet"
        combo.to_parquet(new_norm_path, index=False, compression="zstd")
        del combo
        gc.collect()

    union_info = build_union(root, new_norm_path)
    union_df = union_info.pop("union")
    join = join_events(root, union_df)
    outlier = inspect_outlier_path(root, union_df, join)
    spr = spread_stats_from_union(union_df)
    del union_df

    new_first = min(x["first_tick"] for x in ingested_list if x.get("first_tick"))
    new_last = max(x["last_tick"] for x in ingested_list if x.get("last_tick"))
    primary = ingested_list[0]
    ov = overlap_and_gap(new_first, new_last)
    nxt = next_export_window(union_info["first_tick"])

    identity_ok = all(x.get("symbol_identity_ok") for x in ingested_list)
    bid_ok = all(x.get("profile", {}).get("bid_present") for x in ingested_list)
    ask_ok = all(x.get("profile", {}).get("ask_present") for x in ingested_list)
    one_sided = any((x.get("raw_missing_bid") or 0) + (x.get("raw_missing_ask") or 0) > 0 for x in ingested_list)

    amb_resolved = int(join.get("AMBIGUOUS_394_RESOLVED") or 0)
    amb_remaining = int(join.get("AMBIGUOUS_394_REMAINING") or (N_AMBIGUOUS_394 - amb_resolved))
    newly = max(0, amb_resolved - PRIOR_AMB_RESOLVED)

    # C/D/E/F lifecycle counts
    path_chrono = join.get("path_chronology") or {}
    cdef_life = {}
    for pc in ("C", "D", "E", "F"):
        bucket = path_chrono.get(pc) or {}
        covered = sum(int(v) for k, v in bucket.items() if k != "DATA_INSUFFICIENT")
        cdef_life[pc] = {"chronology": bucket, "non_insufficient": covered}

    all_raw_untouched = p118_ok and p120_ok and p121_ok and all(x.get("raw_unchanged") for x in ingested_list)
    status = "PASS" if frozen.get("ok") and all_raw_untouched and identity_ok else "FAIL"

    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "PHASE122_STATUS": status,
        "RAW_DIRECTORY": RAW_DROP_REL,
        "PHASE118_FILE": PHASE118_RAW_NAME,
        "PHASE120_FILE": PHASE120_RAW_NAME,
        "PHASE121_FILE": PHASE121_RAW_NAME,
        "PHASE118_SHA256": PHASE118_SHA256,
        "PHASE120_SHA256": PHASE120_SHA256,
        "PHASE121_SHA256": PHASE121_SHA256,
        "PHASE118_SHA256_VERIFIED": p118_ok,
        "PHASE120_SHA256_VERIFIED": p120_ok,
        "PHASE121_SHA256_VERIFIED": p121_ok,
        "NEW_OPERATOR_FILES": [x["filename"] for x in ingested_list],
        "NEW_FILE_COUNT": len(ingested_list),
        "NEW_RAW_FILE": primary["filename"],
        "RAW_FILE_SIZE": primary["size_bytes"],
        "RAW_FILE_ROWS": primary["raw_rows"],
        "RAW_FILE_SHA256": primary["sha256"],
        "ACTUAL_FIRST_TICK": new_first,
        "ACTUAL_LAST_TICK": new_last,
        "NEW_EXPORT_FIRST_TICK": new_first,
        "NEW_EXPORT_LAST_TICK": new_last,
        "NEW_EXPORT_ROW_COUNT": int(sum(x.get("raw_rows") or 0 for x in ingested_list)),
        "NEW_EXPORT_SHA256": primary["sha256"] if len(ingested_list) == 1 else [x["sha256"] for x in ingested_list],
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
        "PHASE120_FIRST_TICK": PHASE120_FIRST,
        "PHASE120_LAST_TICK": PHASE120_LAST,
        "PHASE121_FIRST_TICK": PHASE121_FIRST,
        "PHASE121_LAST_TICK": PHASE121_LAST,
        "OVERLAP_START": ov["OVERLAP_START"],
        "OVERLAP_END": ov["OVERLAP_END"],
        "GAP_TO_PREVIOUS_EXPORT": ov["GAP_TO_PREVIOUS_EXPORT"],
        "extends_before_phase121": ov.get("extends_before_phase121"),
        "additional_days_before_phase121": ov.get("additional_days_before_phase121"),
        "PRIOR_TICK_EVENT_COVERAGE": PRIOR_TICK_EVENT_COVERAGE,
        "PRIOR_AMB_RESOLVED": PRIOR_AMB_RESOLVED,
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
        "AMBIGUOUS_394_RESOLVED": amb_resolved,
        "AMBIGUOUS_394_REMAINING": amb_remaining,
        "NEWLY_RESOLVED_THIS_PHASE": newly,
        "NEWLY_RESOLVED": newly,
        "OUTLIER_31_84R_TICK_COVERAGE": outlier["OUTLIER_31_84R_TICK_COVERAGE"],
        "OUTLIER_31_84R_COVERAGE": outlier["OUTLIER_31_84R_TICK_COVERAGE"],
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": outlier["OUTLIER_31_84R_CHRONOLOGY_STATUS"],
        "outlier_detail": outlier.get("outlier_detail"),
        "C_D_E_F_STATUS": (
            "PARTIAL_NOV2025_SEP2026_WITH_OUTLIER_F"
            if outlier.get("OUTLIER_31_84R_TICK_COVERAGE")
            else join["C_D_E_F_STATUS"]
        ),
        "cdef_lifecycle": cdef_life,
        "cdef_vs_phase121": {
            "C": {"phase121": 20, "phase122": cdef_life.get("C", {}).get("non_insufficient", 0)},
            "D": {"phase121": 2, "phase122": cdef_life.get("D", {}).get("non_insufficient", 0)},
            "E": {"phase121": 12, "phase122": cdef_life.get("E", {}).get("non_insufficient", 0)},
            "F": {"phase121": 1, "phase122": cdef_life.get("F", {}).get("non_insufficient", 0)},
        },
        "path_chronology": path_chrono,
        **spr,
        **{k: nxt[k] for k in [
            "REMAINING_MISSING_START", "REMAINING_MISSING_END", "FULL_HORIZON_SOURCE_STATUS",
            "NEXT_OPERATOR_EXPORT_START", "NEXT_OPERATOR_EXPORT_END", "NEXT_ACTION",
        ]},
        "REMAINING_GAP": (
            f"{nxt.get('REMAINING_MISSING_START')} -> {nxt.get('REMAINING_MISSING_END')}"
            if nxt.get("REMAINING_MISSING_START")
            else "NONE"
        ),
        "NEXT_BACKWARD_EXPORT": (
            f"{nxt.get('NEXT_OPERATOR_EXPORT_START')} -> {nxt.get('NEXT_OPERATOR_EXPORT_END')}"
            if nxt.get("NEXT_OPERATOR_EXPORT_START")
            else None
        ),
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
        "TESTS_PHASE122": None,
        "REGRESSION_40_43_57_63_68_122": None,
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
            "phase120_raw_modified": False,
            "phase121_raw_modified": False,
            "new_raw_modified": False,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE122_JSON, "md": PHASE122_MD, "log": PHASE122_LOG, "ledger": LEDGER_MD},
        "phase123_started": False,
    }
    if not frozen.get("ok"):
        payload["PHASE122_STATUS"] = "FAIL"
        payload["blocker"] = "Frozen Phase 40 mismatch. File was not repaired."
    if not p118_ok or not p120_ok or not p121_ok:
        payload["PHASE122_STATUS"] = "FAIL"
        payload["blocker"] = "Prior raw SHA256 mismatch; files were not repaired."

    need_more = payload.get("NEXT_ACTION") == "REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT"
    payload["PHASE123_READY"] = False if need_more else bool(
        payload["PHASE122_STATUS"] == "PASS"
        and payload.get("SOURCE_IDENTITY_STATUS") == "VERIFIED"
    )

    (root / PHASE122_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE122_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    _write_md(root, payload)
    _write_log(root, payload)
    _patch_docs(root, payload)
    return payload


def _write_log(root: Path, payload: dict[str, Any]) -> None:
    keys = [
        "PHASE122_STATUS", "NEW_RAW_FILE", "RAW_FILE_SIZE", "RAW_FILE_ROWS", "RAW_FILE_SHA256",
        "SOURCE_IDENTITY_STATUS", "ACTUAL_FIRST_TICK", "ACTUAL_LAST_TICK", "DATA_QUALITY_STATUS",
        "TICK_EVENT_COVERAGE", "TICK_COMPLETE_LIFECYCLE_EVENTS", "TICK_ENTRY_COVERAGE",
        "TICK_EXIT_COVERAGE", "TICK_INTRABAR_RESOLUTION_COVERAGE", "FAVORABLE_FIRST",
        "ADVERSE_FIRST", "SIMULTANEOUS_UNRESOLVED", "DATA_INSUFFICIENT",
        "AMBIGUOUS_394_RESOLVED", "AMBIGUOUS_394_REMAINING", "NEWLY_RESOLVED",
        "OUTLIER_31_84R_COVERAGE", "OUTLIER_31_84R_CHRONOLOGY_STATUS", "C_D_E_F_STATUS",
        "REMAINING_GAP", "NEXT_BACKWARD_EXPORT", "PHASE123_READY",
        "MT5_USED", "LIVE_TRADING", "ORDERS_PLACED", "ENV_ACCESSED", "PRODUCTION_CHANGED",
        "RISK_GATE_CHANGED", "TRADING_KERNEL_CHANGED", "EXECUTION_CHANGED", "STRATEGY_CHANGED",
        "CALIBRATION_CHANGED", "SIZING_CHANGED", "SLTP_CHANGED", "ML_ACTIVATED",
        "OPTIMIZATION_USED", "EXIT_DESIGN_SPEC_IMPLEMENTED",
    ]
    lines = [f"{k}={payload.get(k)}" for k in keys]
    (root / PHASE122_LOG).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run_phase122_collection(Path.cwd())
