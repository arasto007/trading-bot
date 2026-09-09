"""Phase 27.25 — targeted canonical XAUUSD_i M5 Bid/Ask coverage.

Read-only. Requests historical ticks for the actual dataset range only.
Never overwrites production parquets. Does not change FINAL_GATE or other costs.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.cost_model import detect_spread_mode_from_frame, frame_has_historical_bid_ask
from tradingbot.backtest.dataset_provenance import load_dataset_metadata, metadata_path_for
from tradingbot.backtest.historical_bidask import CANONICAL_SYMBOL, CANONICAL_TIMEFRAME, credentials_contaminated, tape_fingerprint
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    account_identity_snapshot,
    bounded_readonly_attach_once,
    terminal_build_snapshot,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_18_historical_bidask import validate_phase2718_tape
from tradingbot.backtest.phase27_23_bidask_expansion import (
    _copy_ticks_chunk,
    _iso,
    _safe_load_json,
    _sanitize,
    chunk_windows,
    quality_ticks,
)

PHASE2725_JSON = "logs/phase27_25_canonical_bidask_coverage.json"
PHASE2725_MD = "docs_v2/01_truth/PHASE27_25_CANONICAL_BIDASK_COVERAGE.md"
TAPE_PARQUET = "logs/phase27_25_xauusd_i_m5_bidask.parquet"
TAPE_META = "logs/phase27_25_xauusd_i_m5_bidask.metadata.json"
RAW_TICKS_PARQUET = "logs/phase27_25_xauusd_i_ticks.parquet"
PRODUCTION_M5 = "data/XAUUSD_i_5m.parquet"
PRODUCTION_H4 = "data/XAUUSD_i_4h.parquet"

REQUIRED_ENV = "REAL"
REQUIRED_BROKER = "LiteFinance Global LLC"
REQUIRED_SERVER = "LiteFinance-MT5-Live"
CHUNK_HOURS = 6
MAX_TICKS_PER_CHUNK = 100_000
MAX_CHUNKS = 90
MAX_TOTAL_TICKS = 2_000_000
MIN_SPLIT_HOURS = 1

FULL_CANONICAL_COVERAGE = "FULL_CANONICAL_COVERAGE"
PARTIAL_CANONICAL_COVERAGE = "PARTIAL_CANONICAL_COVERAGE"
NO_CANONICAL_COVERAGE = "NO_CANONICAL_COVERAGE"
BLOCKED_PENDING_DATA = "BLOCKED_PENDING_DATA"
PROVEN = "PROVEN"
PARTIAL = "PARTIAL"
BLOCKED = "BLOCKED"
PROVEN_FOR_CANONICAL_DATASET = "PROVEN_FOR_CANONICAL_DATASET"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "UNKNOWN"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment_matches(account: dict[str, Any]) -> tuple[bool, str]:
    env = str(account.get("trade_mode_label") or "UNKNOWN")
    broker = str(account.get("broker") or "UNKNOWN")
    server = str(account.get("server") or "UNKNOWN")
    if env != REQUIRED_ENV:
        return False, f"environment {env} is not {REQUIRED_ENV}"
    if broker != REQUIRED_BROKER:
        return False, f"broker {broker} is not {REQUIRED_BROKER}"
    if server != REQUIRED_SERVER:
        return False, f"server {server} is not {REQUIRED_SERVER}"
    return True, "ok"


def classify_canonical_coverage(*, covered_bars: int, dataset_bars: int, collection_attempted: bool) -> str:
    """Exactly one coverage class. Full only if every dataset M5 bar is covered."""
    if dataset_bars <= 0:
        return BLOCKED_PENDING_DATA
    if covered_bars <= 0:
        return NO_CANONICAL_COVERAGE if collection_attempted else BLOCKED_PENDING_DATA
    if covered_bars >= dataset_bars:
        return FULL_CANONICAL_COVERAGE
    return PARTIAL_CANONICAL_COVERAGE


def historical_spread_status(coverage: str) -> str:
    if coverage == FULL_CANONICAL_COVERAGE:
        return PROVEN_FOR_CANONICAL_DATASET
    if coverage == PARTIAL_CANONICAL_COVERAGE:
        return PARTIAL
    return BLOCKED_PENDING_DATA


def inspect_canonical_dataset(root: Path) -> dict[str, Any]:
    path = root / PRODUCTION_M5
    if not path.is_file():
        return {"exists": False, "path": PRODUCTION_M5, "error": f"{PRODUCTION_M5} does not exist"}
    df = pd.read_parquet(path)
    idx = pd.to_datetime(df.index, utc=True) if isinstance(df.index, pd.DatetimeIndex) else None
    if idx is None:
        return {"exists": True, "path": PRODUCTION_M5, "error": "index is not DatetimeIndex", "rows": int(len(df))}
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    spacing = None
    if len(idx) >= 2:
        spacing = str(pd.Series(idx).diff().dropna().median())
    sidecar_path = metadata_path_for(path)
    sidecar = {}
    try:
        meta = load_dataset_metadata(path)
        sidecar = meta.to_dict() if meta is not None else {}
    except Exception as exc:
        sidecar = {"error": str(exc)}
    inferred_tf = CANONICAL_TIMEFRAME if spacing and "0 days 00:05:00" in str(spacing) else sidecar.get("timeframe")
    return {
        "exists": True,
        "path": PRODUCTION_M5,
        "sidecar_path": str(sidecar_path.as_posix()) if sidecar_path else None,
        "sidecar_present": sidecar_path.is_file(),
        "symbol": sidecar.get("dataset_symbol") or CANONICAL_SYMBOL,
        "configured_instrument_symbol": sidecar.get("configured_instrument_symbol"),
        "timeframe": inferred_tf,
        "timeframe_sidecar": sidecar.get("timeframe"),
        "start_utc": _iso(idx.min()),
        "end_utc": _iso(idx.max()),
        "rows": int(len(df)),
        "timezone": "UTC",
        "fingerprint": _file_sha256(path),
        "sidecar_fingerprint": sidecar.get("fingerprint"),
        "spread_mode": sidecar.get("spread_mode") or detect_spread_mode_from_frame(df).value,
        "spread_source": sidecar.get("spread_source"),
        "historical_bid_ask_available": bool(sidecar.get("historical_bid_ask_available")),
        "mapping_status": sidecar.get("mapping_status"),
        "dataset_symbol_map": sidecar.get("dataset_symbol_map") or {},
        "provenance_summary": sidecar.get("provenance_summary"),
        "account_environment": sidecar.get("account_environment"),
        "columns": [str(c) for c in df.columns],
        "has_bid_ask_columns": bool(frame_has_historical_bid_ask(df)),
        "monotonic": bool(idx.is_monotonic_increasing),
        "duplicate_timestamps": int(idx.duplicated().sum()),
        "median_bar_spacing": spacing,
    }


def collect_ticks_for_range(
    symbol: str,
    date_from: datetime,
    date_to: datetime,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    pending = chunk_windows(date_from, date_to, CHUNK_HOURS)
    frames: list[pd.DataFrame] = []
    chunk_log: list[dict[str, Any]] = []
    total = 0
    calls = 0
    truncated_chunks = 0
    empty_chunks = 0
    stop_reason = None
    while pending:
        if calls >= MAX_CHUNKS:
            stop_reason = "max_chunks_reached"
            break
        if total >= MAX_TOTAL_TICKS:
            stop_reason = "max_total_ticks_reached"
            break
        start, end = pending.pop(0)
        calls += 1
        df, meta = _copy_ticks_chunk(symbol, start, end)
        hours = (end - start).total_seconds() / 3600.0
        rows = int(meta.get("row_count") or 0)
        if df is not None and rows >= MAX_TICKS_PER_CHUNK and hours > MIN_SPLIT_HOURS:
            mid = start + (end - start) / 2
            pending.insert(0, (mid, end))
            pending.insert(0, (start, mid))
            chunk_log.append({**meta, "split": True, "reason": "chunk_hit_tick_cap"})
            continue
        if df is not None and rows > MAX_TICKS_PER_CHUNK:
            df = df.iloc[:MAX_TICKS_PER_CHUNK].copy()
            rows = int(len(df))
            meta["truncated"] = True
            truncated_chunks += 1
        if df is None or df.empty:
            empty_chunks += 1
            chunk_log.append({**meta, "empty": True})
            continue
        remain = MAX_TOTAL_TICKS - total
        if remain <= 0:
            stop_reason = "max_total_ticks_reached"
            break
        if rows > remain:
            df = df.iloc[:remain].copy()
            rows = int(len(df))
            meta["truncated"] = True
            truncated_chunks += 1
            stop_reason = "max_total_ticks_reached"
        frames.append(df)
        total += rows
        chunk_log.append(meta)
        if stop_reason:
            break
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not combined.empty and "time" in combined.columns:
        combined = combined.drop_duplicates(subset=["time", "bid", "ask"], keep="first")
        combined = combined.sort_values("time").reset_index(drop=True)
    return (combined if not combined.empty else None), {
        "ok": not combined.empty,
        "method": "copy_ticks_range bounded 6-hour chunks over canonical dataset range; no symbol_select",
        "chunk_hours": CHUNK_HOURS,
        "max_ticks_per_chunk": MAX_TICKS_PER_CHUNK,
        "max_chunks": MAX_CHUNKS,
        "max_total_ticks": MAX_TOTAL_TICKS,
        "chunk_calls": calls,
        "empty_chunks": empty_chunks,
        "truncated_chunks": truncated_chunks,
        "stop_reason": stop_reason,
        "requested_from_utc": _iso(date_from),
        "requested_to_utc": _iso(date_to),
        "tick_count": int(len(combined)),
        "chunk_summaries": [
            {
                "date_from_utc": c.get("date_from_utc"),
                "date_to_utc": c.get("date_to_utc"),
                "row_count": c.get("row_count"),
                "empty": c.get("empty", False),
                "split": c.get("split", False),
                "truncated": c.get("truncated", False),
                "error": c.get("error"),
            }
            for c in chunk_log
        ],
    }


def ticks_to_m5_coverage_bars(ticks: pd.DataFrame) -> pd.DataFrame:
    if ticks is None or ticks.empty:
        return pd.DataFrame()
    df = ticks.copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
    df = df.sort_index()
    bid = pd.to_numeric(df["bid"], errors="coerce")
    ask = pd.to_numeric(df["ask"], errors="coerce")
    spread = ask - bid
    ts = df.index.to_series()
    bars = pd.DataFrame(
        {
            "bid": bid.resample("5min").last(),
            "ask": ask.resample("5min").last(),
            "tick_count": df.resample("5min").size(),
            "first_timestamp": ts.resample("5min").min(),
            "last_timestamp": ts.resample("5min").max(),
            "spread_min": spread.resample("5min").min(),
            "spread_max": spread.resample("5min").max(),
        }
    )
    bars = bars.dropna(subset=["bid", "ask"])
    valid = (bars["bid"] > 0) & (bars["ask"] > 0) & (bars["ask"] >= bars["bid"])
    return bars.loc[valid]


def uncovered_intervals(dataset_idx: pd.DatetimeIndex, covered_idx: pd.DatetimeIndex) -> list[dict[str, Any]]:
    missing = dataset_idx.difference(covered_idx).sort_values()
    if len(missing) == 0:
        return []
    intervals: list[dict[str, Any]] = []
    start = missing[0]
    prev = missing[0]
    count = 1
    step = pd.Timedelta(minutes=5)
    for ts in missing[1:]:
        if ts - prev <= step:
            count += 1
            prev = ts
            continue
        intervals.append(
            {
                "start_utc": _iso(start),
                "end_utc": _iso(prev),
                "bars": count,
                "duration_hours": round((prev - start).total_seconds() / 3600.0, 3),
            }
        )
        start = ts
        prev = ts
        count = 1
    intervals.append(
        {
            "start_utc": _iso(start),
            "end_utc": _iso(prev),
            "bars": count,
            "duration_hours": round((prev - start).total_seconds() / 3600.0, 3),
        }
    )
    return intervals


def compare_coverage(dataset: pd.DataFrame, evidence: pd.DataFrame | None) -> dict[str, Any]:
    ds_idx = pd.to_datetime(dataset.index, utc=True)
    if evidence is None or evidence.empty:
        gaps = uncovered_intervals(ds_idx, pd.DatetimeIndex([], tz="UTC"))
        largest = max(gaps, key=lambda g: g["bars"]) if gaps else None
        return {
            "dataset_start": _iso(ds_idx.min()),
            "dataset_end": _iso(ds_idx.max()),
            "evidence_start": None,
            "evidence_end": None,
            "covered_M5_bars": 0,
            "dataset_M5_bars": int(len(ds_idx)),
            "coverage_percent": 0.0,
            "uncovered_intervals": gaps,
            "uncovered_interval_count": len(gaps),
            "largest_gap": largest,
            "overlap_start": None,
            "overlap_end": None,
            "canonical_fully_covered": False,
        }
    ev_idx = pd.to_datetime(evidence.index, utc=True)
    covered = ds_idx.intersection(ev_idx)
    # Require valid bid/ask on the evidence row.
    sufficient = []
    for ts in covered:
        row = evidence.loc[ts]
        if float(row["bid"]) > 0 and float(row["ask"]) > 0 and float(row["ask"]) >= float(row["bid"]):
            sufficient.append(ts)
    sufficient_idx = pd.DatetimeIndex(sufficient, tz="UTC")
    gaps = uncovered_intervals(ds_idx, sufficient_idx)
    largest = max(gaps, key=lambda g: g["bars"]) if gaps else None
    overlap = len(sufficient_idx) > 0
    return {
        "dataset_start": _iso(ds_idx.min()),
        "dataset_end": _iso(ds_idx.max()),
        "evidence_start": _iso(ev_idx.min()),
        "evidence_end": _iso(ev_idx.max()),
        "covered_M5_bars": int(len(sufficient_idx)),
        "dataset_M5_bars": int(len(ds_idx)),
        "coverage_percent": round(100.0 * len(sufficient_idx) / len(ds_idx), 4) if len(ds_idx) else 0.0,
        "uncovered_intervals": gaps[:40],
        "uncovered_interval_count": len(gaps),
        "largest_gap": largest,
        "overlap_start": _iso(sufficient_idx.min()) if overlap else None,
        "overlap_end": _iso(sufficient_idx.max()) if overlap else None,
        "canonical_fully_covered": bool(len(sufficient_idx) == len(ds_idx) and len(ds_idx) > 0),
    }


def run_phase27_25_canonical_bidask_coverage(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    before = build_immutability_manifest(root)
    inspected = inspect_canonical_dataset(root)
    if not inspected.get("exists"):
        payload = {
            "schema_version": 1,
            "phase": "27.25",
            "status": "PASS",
            "timestamp": timestamp,
            "classification": BLOCKED_PENDING_DATA,
            "historical_spread": BLOCKED_PENDING_DATA,
            "canonical_dataset": inspected,
            "production_parquet_updated": False,
            "phase27_16_final_gate_unchanged": str((_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or "UNKNOWN"),
            "deferred": ["Phase 27.26+ — not started"],
        }
        (root / PHASE2725_JSON).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        _write_md(root, payload)
        return payload

    dataset = pd.read_parquet(root / PRODUCTION_M5)
    ds_start = pd.Timestamp(inspected["start_utc"]).tz_convert("UTC").to_pydatetime()
    ds_end = pd.Timestamp(inspected["end_utc"]).tz_convert("UTC").to_pydatetime() + timedelta(minutes=5)

    attach = bounded_readonly_attach_once()
    account = {"trade_mode_label": "UNKNOWN", "broker": "UNKNOWN", "server": "UNKNOWN"}
    terminal = {"build": "UNKNOWN"}
    env_ok = False
    env_reason = attach.get("error") or "not_attached"
    collect_meta: dict[str, Any] = {"attempted": False}
    bars = None
    tick_quality: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    tape_meta: dict[str, Any] = {}
    tape_path = None
    raw_path = None

    if attach.get("ok"):
        import MetaTrader5 as mt5

        account = account_identity_snapshot(mt5)
        terminal = terminal_build_snapshot(mt5)
        env_ok, env_reason = environment_matches(account)
        if env_ok:
            info = mt5.symbol_info(CANONICAL_SYMBOL)
            if info is None:
                collect_meta["error"] = f"{CANONICAL_SYMBOL} not visible via symbol_info (symbol_select not called)"
            else:
                collect_meta["attempted"] = True
                ticks, tick_meta = collect_ticks_for_range(CANONICAL_SYMBOL, ds_start, ds_end)
                collect_meta.update(tick_meta)
                if ticks is not None and not ticks.empty:
                    tick_quality = quality_ticks(ticks)
                    valid = (
                        (pd.to_numeric(ticks["bid"], errors="coerce") > 0)
                        & (pd.to_numeric(ticks["ask"], errors="coerce") > 0)
                        & (pd.to_numeric(ticks["ask"], errors="coerce") >= pd.to_numeric(ticks["bid"], errors="coerce"))
                    )
                    clean = ticks.loc[valid].copy()
                    bars = ticks_to_m5_coverage_bars(clean)
                    if bars is not None and not bars.empty:
                        fp = tape_fingerprint(bars[["bid", "ask"]])
                        tape_meta = {
                            "symbol": CANONICAL_SYMBOL,
                            "timeframe": CANONICAL_TIMEFRAME,
                            "source": "mt5_copy_ticks_range",
                            "collection_method": "copy_ticks_range bounded chunks over canonical dataset range",
                            "broker": account.get("broker"),
                            "server": account.get("server"),
                            "row_count": int(len(bars)),
                            "tick_count": int(len(clean)),
                            "time_range": {
                                "start": _iso(bars.index.min()),
                                "end": _iso(bars.index.max()),
                                "timezone": "UTC",
                            },
                            "fingerprint": fp,
                            "utc_timestamp": timestamp,
                            "current_bid_ask_tick": False,
                            "ohlc_spread": False,
                            "proxy_spread": False,
                            "not_a_production_dataset": True,
                        }
                        validation = validate_phase2718_tape(
                            bars[["bid", "ask"]],
                            symbol=CANONICAL_SYMBOL,
                            timeframe=CANONICAL_TIMEFRAME,
                            provenance=tape_meta,
                        )
                        if validation.get("ok") and not credentials_contaminated(tape_meta):
                            out_pq = root / TAPE_PARQUET
                            out_pq.parent.mkdir(parents=True, exist_ok=True)
                            bars.to_parquet(out_pq)
                            (root / TAPE_META).write_text(
                                json.dumps(_sanitize(tape_meta), indent=2, sort_keys=True),
                                encoding="utf-8",
                            )
                            raw = pd.DataFrame(
                                {
                                    "time_utc": pd.to_datetime(clean["time"], unit="s", utc=True),
                                    "bid": pd.to_numeric(clean["bid"], errors="coerce"),
                                    "ask": pd.to_numeric(clean["ask"], errors="coerce"),
                                    "symbol": CANONICAL_SYMBOL,
                                    "source": "mt5_copy_ticks_range",
                                }
                            )
                            if "flags" in clean.columns:
                                raw["flags"] = clean["flags"].to_numpy()
                            raw.to_parquet(root / RAW_TICKS_PARQUET)
                            tape_path = TAPE_PARQUET
                            raw_path = RAW_TICKS_PARQUET
                else:
                    collect_meta["error"] = tick_meta.get("error") or "no historical ticks in canonical range"
        else:
            collect_meta["error"] = env_reason
    else:
        collect_meta["error"] = attach.get("error") or "MT5 not attached"

    originals_untouched, issues = verify_immutability(before, base_dir=root)
    after_hash = _file_sha256(root / PRODUCTION_M5)
    production_unchanged = after_hash == inspected["fingerprint"]
    cmp_ = compare_coverage(dataset, bars)
    classification = classify_canonical_coverage(
        covered_bars=int(cmp_["covered_M5_bars"]),
        dataset_bars=int(cmp_["dataset_M5_bars"]),
        collection_attempted=bool(collect_meta.get("attempted")),
    )
    prior_exists = (root / "logs/phase27_23_xauusd_i_m5_bidask.parquet").is_file() or (
        root / "logs/phase27_18_xauusd_i_m5_bidask.parquet"
    ).is_file()
    this_exists = bars is not None and not bars.empty
    abc = {
        "A_historical_bid_ask_exists": PROVEN if (this_exists or prior_exists) else BLOCKED,
        "B_canonical_dataset_partially_covered": PROVEN
        if 0 < int(cmp_["covered_M5_bars"]) < int(cmp_["dataset_M5_bars"])
        else BLOCKED,
        "C_canonical_dataset_fully_covered": PROVEN if cmp_["canonical_fully_covered"] else BLOCKED,
        "D_production_parquet_updated": False,
    }
    final_gate = str((_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or "UNKNOWN")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.25",
        "status": "PASS" if originals_untouched and production_unchanged else "FAIL",
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "canonical_symbol": CANONICAL_SYMBOL,
        "canonical_timeframe": CANONICAL_TIMEFRAME,
        "canonical_dataset": inspected,
        "environment_verified": env_ok,
        "environment_reason": env_reason,
        "mt5_attach": {
            "ok": attach.get("ok"),
            "error": attach.get("error"),
            "environment": account.get("trade_mode_label"),
            "broker": account.get("broker"),
            "server": account.get("server"),
            "started": False,
            "restarted": False,
        },
        "terminal": terminal,
        "collection": collect_meta,
        "tick_quality": tick_quality,
        "tape": {
            "path": tape_path,
            "raw_ticks_path": raw_path,
            "m5_bar_count": int(len(bars)) if bars is not None and not bars.empty else 0,
            "tick_count": int(tick_quality.get("tick_count") or collect_meta.get("tick_count") or 0),
            "start_utc": cmp_.get("evidence_start"),
            "end_utc": cmp_.get("evidence_end"),
            "fingerprint": tape_meta.get("fingerprint"),
            "validation": validation,
            "production_dataset": False,
        },
        "coverage_matrix": cmp_,
        "classification": classification,
        "historical_spread": historical_spread_status(classification),
        "abc": abc,
        "production_parquet_updated": False,
        "production_spread_mode_unchanged": inspected.get("spread_mode"),
        "original_datasets_untouched": originals_untouched,
        "protected_production_untouched": production_unchanged,
        "immutability_issues": issues,
        "other_costs_collected": False,
        "phase27_16_final_gate_unchanged": final_gate,
        "complete_costs_required_weakened": False,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "mt5_restarted": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "sizing_modified": False,
            "rr_modified": False,
            "ml_modified": False,
            "production_parquet_overwritten": not production_unchanged,
            "proxy_converted_to_dataset": False,
            "commission_collected": False,
            "swap_collected": False,
            "slippage_collected": False,
            "execution_collected": False,
            "phase_27_26_started": False,
        },
        "deferred": ["Phase 27.26+ — not started"],
    }
    if abc["D_production_parquet_updated"] or payload["production_parquet_updated"]:
        payload["status"] = "FAIL"
    if classification == FULL_CANONICAL_COVERAGE and not cmp_["canonical_fully_covered"]:
        payload["status"] = "FAIL"
    if credentials_contaminated(payload):
        payload["status"] = "FAIL"

    out = root / PHASE2725_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_25_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_25_canonical_bidask_coverage(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    ds = payload.get("canonical_dataset") or {}
    tape = payload.get("tape") or {}
    cov = payload.get("coverage_matrix") or {}
    abc = payload.get("abc") or {}
    md = f"""# Phase 27.25 — Targeted Canonical Dataset Bid/Ask Coverage

**Status:** {payload.get('status')}  
**Classification:** `{payload.get('classification')}`  
**historical_spread:** `{payload.get('historical_spread')}`  
**Artifact:** `{PHASE2725_JSON}`  
**Collection timestamp UTC:** `{payload.get('timestamp')}`

Read-only. No MT5 start/restart, orders, `symbol_select`, `.env`, or production parquet overwrite.

## Canonical dataset

| Field | Value |
|---|---|
| path | `{ds.get('path')}` |
| symbol | `{ds.get('symbol')}` |
| timeframe | `{ds.get('timeframe')}` |
| start UTC | `{ds.get('start_utc')}` |
| end UTC | `{ds.get('end_utc')}` |
| rows | `{ds.get('rows')}` |
| timezone | `{ds.get('timezone')}` |
| fingerprint | `{ds.get('fingerprint')}` |
| spread mode | `{ds.get('spread_mode')}` |
| provenance | `{ds.get('provenance_summary')}` |

## Historical Bid/Ask obtained

| Field | Value |
|---|---|
| ticks | `{tape.get('tick_count')}` |
| M5 evidence bars | `{tape.get('m5_bar_count')}` |
| evidence start | `{tape.get('start_utc')}` |
| evidence end | `{tape.get('end_utc')}` |
| fingerprint | `{tape.get('fingerprint')}` |
| logs tape | `{tape.get('path')}` |

Requested range = actual dataset range (plus one M5 bar to close the last interval). Not a generic 7-day window.

## Coverage matrix

| Field | Value |
|---|---|
| covered M5 bars | `{cov.get('covered_M5_bars')}` / `{cov.get('dataset_M5_bars')}` |
| coverage percent | `{cov.get('coverage_percent')}` |
| overlap | `{cov.get('overlap_start')}` → `{cov.get('overlap_end')}` |
| uncovered intervals | `{cov.get('uncovered_interval_count')}` |
| largest gap | `{cov.get('largest_gap')}` |
| fully covered | `{cov.get('canonical_fully_covered')}` |

## A/B/C/D

| Class | Result |
|---|---|
| A. Historical Bid/Ask exists | **{abc.get('A_historical_bid_ask_exists')}** |
| B. Canonical dataset partially covered | **{abc.get('B_canonical_dataset_partially_covered')}** |
| C. Canonical dataset fully covered | **{abc.get('C_canonical_dataset_fully_covered')}** |
| D. Production parquet updated | **{abc.get('D_production_parquet_updated')}** |

Production spread mode remains `{payload.get('production_spread_mode_unchanged')}`. PROXY was not converted to DATASET.

## Other costs

Not collected. Commission, swap, slippage, and execution remain separate blockers.

## Production

**BLOCKED.** COMPLETE_COSTS_REQUIRED was not weakened. FINAL_GATE remains `{payload.get('phase27_16_final_gate_unchanged')}`. Phase 27.26+ not started.

## Next

STOP after Phase 27.25.
"""
    (root / PHASE2725_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.25 canonical bid/ask coverage:** `{PHASE2725_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.24 execution/cost forensics:** `logs/phase27_24_execution_cost_forensics.json` — swap BROKER_RATE_ONLY; realized slippage UNKNOWN unless genuine requested/fill pairs exist; execution not SimulatedBroker",
            "**Phase 27.24 execution/cost forensics:** `logs/phase27_24_execution_cost_forensics.json` — swap BROKER_RATE_ONLY; realized slippage UNKNOWN unless genuine requested/fill pairs exist; execution not SimulatedBroker  \n"
            + pointer
            + f" — classification `{payload.get('classification')}`; production parquet unchanged; C full coverage "
            + str(payload.get("abc", {}).get("C_canonical_dataset_fully_covered")),
        )
    old = (
        "| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed. "
        "Phase 27.23 production still PROXY; logs tape `DATASET`; A=PROVEN B=PROVEN C=BLOCKED |"
    )
    new = (
        "| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed. "
        f"Phase 27.25 `{payload.get('classification')}`; historical_spread `{payload.get('historical_spread')}`; "
        f"production parquet unchanged; C={payload.get('abc', {}).get('C_canonical_dataset_fully_covered')} |"
    )
    if old in text:
        text = text.replace(old, new)
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
