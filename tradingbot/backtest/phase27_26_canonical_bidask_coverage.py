"""Phase 27.26 — complete canonical XAUUSD_i M5 Bid/Ask coverage.

Merges Phase 27.25 evidence with new ticks for missing intervals.
Does not overwrite the 27.25 tape or the production parquet.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.historical_bidask import (
    CANONICAL_SYMBOL,
    CANONICAL_TIMEFRAME,
    credentials_contaminated,
    tape_fingerprint,
)
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
    _git_head,
    _iso,
    _safe_load_json,
    _sanitize,
    chunk_windows,
    quality_ticks,
)
from tradingbot.backtest.phase27_25_canonical_bidask_coverage import (
    BLOCKED,
    BLOCKED_PENDING_DATA,
    FULL_CANONICAL_COVERAGE,
    NO_CANONICAL_COVERAGE,
    PARTIAL,
    PARTIAL_CANONICAL_COVERAGE,
    PRODUCTION_M5,
    PROVEN,
    PROVEN_FOR_CANONICAL_DATASET,
    RAW_TICKS_PARQUET as PHASE2725_RAW,
    TAPE_PARQUET as PHASE2725_TAPE,
    _file_sha256,
    classify_canonical_coverage,
    compare_coverage,
    environment_matches,
    inspect_canonical_dataset,
    ticks_to_m5_coverage_bars,
    uncovered_intervals,
)

PHASE2726_JSON = "logs/phase27_26_canonical_bidask_coverage.json"
PHASE2726_MD = "docs_v2/01_truth/PHASE27_26_CANONICAL_BIDASK_COVERAGE.md"
TAPE_PARQUET = "logs/phase27_26_xauusd_i_m5_bidask.parquet"
TAPE_META = "logs/phase27_26_xauusd_i_m5_bidask.metadata.json"
RAW_TICKS_PARQUET = "logs/phase27_26_xauusd_i_ticks.parquet"

REQUIRED_ENV = "REAL"
CHUNK_HOURS = 3
MAX_TICKS_PER_CHUNK = 100_000
MAX_CHUNKS = 80
MAX_TOTAL_TICKS = 2_000_000
MIN_SPLIT_HOURS = 1
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "status",
    "collection_timestamp_utc",
    "account_type",
    "broker",
    "server",
    "terminal_build",
    "symbol",
    "dataset_path",
    "dataset_fingerprint_before",
    "dataset_fingerprint_after",
    "dataset_rows",
    "dataset_start_utc",
    "dataset_end_utc",
    "requested_start_utc",
    "requested_end_utc",
    "tick_count",
    "invalid_tick_count",
    "evidence_start_utc",
    "evidence_end_utc",
    "covered_bar_count",
    "total_bar_count",
    "coverage_percent",
    "fully_covered",
    "uncovered_intervals",
    "largest_gap",
    "collection_stop_reason",
    "existing_evidence_used",
    "production_parquet_changed",
    "historical_spread_classification",
    "final_classification",
    "errors",
    "operator_dependency",
    "provenance",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def historical_spread_status(coverage: str) -> str:
    if coverage == FULL_CANONICAL_COVERAGE:
        return PROVEN_FOR_CANONICAL_DATASET
    if coverage == PARTIAL_CANONICAL_COVERAGE:
        return PARTIAL
    return BLOCKED


def normalize_ticks(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "time" not in out.columns and "time_utc" in out.columns:
        ts = pd.to_datetime(out["time_utc"], utc=True)
        out["time"] = ts.astype("int64") // 10**9
    return out


def merge_tick_frames(existing: pd.DataFrame | None, new: pd.DataFrame | None) -> pd.DataFrame:
    """Deterministic concat + drop_duplicates. Never fabricate bid or ask."""
    frames = []
    for frame in (existing, new):
        norm = normalize_ticks(frame)
        if norm.empty:
            continue
        if "bid" not in norm.columns or "ask" not in norm.columns:
            continue
        bid = pd.to_numeric(norm["bid"], errors="coerce")
        ask = pd.to_numeric(norm["ask"], errors="coerce")
        keep = bid.notna() & ask.notna() & (bid > 0) & (ask > 0) & (ask >= bid)
        frames.append(norm.loc[keep])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    subset = [c for c in ("time", "bid", "ask") if c in out.columns]
    if subset:
        out = out.drop_duplicates(subset=subset, keep="first")
    if "time" in out.columns:
        out = out.sort_values("time")
    return out.reset_index(drop=True)


def classify_gap_kind(start_utc: str, end_utc: str, *, collected_through: str | None, stop_reason: str | None) -> str:
    start = pd.Timestamp(start_utc)
    end = pd.Timestamp(end_utc)
    days = pd.date_range(start, end, freq="5min", tz="UTC") if end >= start else pd.DatetimeIndex([], tz="UTC")
    if len(days) and all(ts.weekday() >= 5 for ts in days):
        return "market_closure_weekend"
    if collected_through:
        through = pd.Timestamp(collected_through)
        if start > through and stop_reason == "max_total_ticks_reached":
            return "unrequested_budget"
    if start.weekday() < 5 and end.weekday() < 5:
        return "technical_or_unavailable"
    return "mixed_or_session_break"


def annotate_gaps(
    gaps: list[dict[str, Any]],
    *,
    collected_through: str | None,
    stop_reason: str | None,
) -> list[dict[str, Any]]:
    out = []
    for gap in gaps:
        row = dict(gap)
        row["kind"] = classify_gap_kind(
            str(gap.get("start_utc")),
            str(gap.get("end_utc")),
            collected_through=collected_through,
            stop_reason=stop_reason,
        )
        out.append(row)
    return out


def ohlc_signature(df: pd.DataFrame) -> dict[str, Any]:
    idx = pd.to_datetime(df.index, utc=True)
    cols = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    raw = df[cols].to_csv(index=True).encode("utf-8") if cols else b""
    import hashlib

    return {
        "rows": int(len(df)),
        "start_utc": _iso(idx.min()) if len(idx) else None,
        "end_utc": _iso(idx.max()) if len(idx) else None,
        "ohlc_sha256": hashlib.sha256(raw).hexdigest(),
    }


def collect_ticks_bounded(
    symbol: str,
    date_from: datetime,
    date_to: datetime,
    *,
    already: int = 0,
    chunk_hours: int = CHUNK_HOURS,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    pending = chunk_windows(date_from, date_to, chunk_hours)
    frames: list[pd.DataFrame] = []
    chunk_log: list[dict[str, Any]] = []
    total = already
    calls = 0
    truncated = 0
    empty = 0
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
        if df is None or df.empty:
            empty += 1
            chunk_log.append({**meta, "empty": True})
            continue
        if rows > MAX_TICKS_PER_CHUNK:
            df = df.iloc[:MAX_TICKS_PER_CHUNK].copy()
            rows = int(len(df))
            meta["truncated"] = True
            truncated += 1
        remain = MAX_TOTAL_TICKS - total
        if rows > remain:
            df = df.iloc[:remain].copy()
            rows = int(len(df))
            meta["truncated"] = True
            truncated += 1
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
        "method": "copy_ticks_range bounded 3-hour chunks over missing canonical intervals; no symbol_select",
        "chunk_hours": chunk_hours,
        "chunk_calls": calls,
        "empty_chunks": empty,
        "truncated_chunks": truncated,
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


def _load_existing_ticks(root: Path) -> tuple[pd.DataFrame, bool]:
    raw_path = root / PHASE2725_RAW
    if raw_path.is_file():
        try:
            return normalize_ticks(pd.read_parquet(raw_path)), True
        except (OSError, ValueError):
            pass
    return pd.DataFrame(), False


def run_phase27_26_canonical_bidask_coverage(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    errors: list[str] = []
    inspected = inspect_canonical_dataset(root)
    if not inspected.get("exists"):
        payload = {
            "phase": "27.26",
            "status": "BLOCKED",
            "collection_timestamp_utc": timestamp,
            "final_classification": BLOCKED_PENDING_DATA,
            "historical_spread_classification": BLOCKED,
            "errors": [inspected.get("error") or "canonical dataset missing"],
            "production_parquet_changed": False,
            "operator_dependency": False,
        }
        (root / PHASE2726_JSON).parent.mkdir(parents=True, exist_ok=True)
        (root / PHASE2726_JSON).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        _write_md(root, payload)
        return payload

    dataset_path = root / PRODUCTION_M5
    dataset = pd.read_parquet(dataset_path)
    fp_before = inspected["fingerprint"]
    sig_before = ohlc_signature(dataset)
    before_manifest = build_immutability_manifest(root)
    tape_25_before = _file_sha256(root / PHASE2725_TAPE) if (root / PHASE2725_TAPE).is_file() else None

    existing_ticks, existing_used = _load_existing_ticks(root)
    existing_bars = None
    if (root / PHASE2725_TAPE).is_file():
        try:
            existing_bars = pd.read_parquet(root / PHASE2725_TAPE)
        except (OSError, ValueError):
            existing_bars = None

    prior_cov = compare_coverage(dataset, existing_bars if existing_bars is not None and not existing_bars.empty else None)
    ds_start = pd.Timestamp(inspected["start_utc"]).tz_convert("UTC").to_pydatetime()
    ds_end = pd.Timestamp(inspected["end_utc"]).tz_convert("UTC").to_pydatetime() + timedelta(minutes=5)

    attach = bounded_readonly_attach_once()
    account = {"trade_mode_label": "UNKNOWN", "broker": "UNKNOWN", "server": "UNKNOWN"}
    terminal = {"build": "UNKNOWN"}
    env_ok = False
    env_reason = attach.get("error") or "not_attached"
    collect_meta: dict[str, Any] = {"attempted": False, "windows": []}
    new_ticks = None
    operator_dependency = False
    status = "PASS"

    if attach.get("ok"):
        import MetaTrader5 as mt5

        account = account_identity_snapshot(mt5)
        terminal = terminal_build_snapshot(mt5)
        env_ok, env_reason = environment_matches(account)
        if not env_ok:
            status = "BLOCKED"
            operator_dependency = True
            errors.append(env_reason)
            collect_meta["error"] = env_reason
        elif mt5.symbol_info(CANONICAL_SYMBOL) is None:
            collect_meta["error"] = f"{CANONICAL_SYMBOL} not visible via symbol_info (symbol_select not called)"
            errors.append(collect_meta["error"])
            status = "PASS_WITH_DEFERRAL"
        else:
            collect_meta["attempted"] = True
            windows: list[tuple[datetime, datetime]] = []
            if prior_cov["uncovered_intervals"]:
                for gap in prior_cov["uncovered_intervals"]:
                    g0 = pd.Timestamp(gap["start_utc"]).tz_convert("UTC").to_pydatetime()
                    g1 = pd.Timestamp(gap["end_utc"]).tz_convert("UTC").to_pydatetime() + timedelta(minutes=5)
                    windows.append((g0, g1))
            else:
                windows.append((ds_start, ds_end))
            frames: list[pd.DataFrame] = []
            already = 0
            stop_reason = None
            for w0, w1 in windows:
                if already >= MAX_TOTAL_TICKS:
                    stop_reason = "max_total_ticks_reached"
                    break
                part, meta = collect_ticks_bounded(CANONICAL_SYMBOL, w0, w1, already=already)
                collect_meta["windows"].append(meta)
                if part is not None and not part.empty:
                    frames.append(part)
                    already += int(len(part))
                if meta.get("stop_reason"):
                    stop_reason = meta["stop_reason"]
                    if stop_reason == "max_total_ticks_reached":
                        break
            if frames:
                new_ticks = pd.concat(frames, ignore_index=True)
            collect_meta["stop_reason"] = stop_reason
            collect_meta["new_tick_count"] = int(len(new_ticks)) if new_ticks is not None else 0
    else:
        status = "BLOCKED"
        operator_dependency = True
        errors.append(attach.get("error") or "MT5 not attached")
        collect_meta["error"] = errors[-1]

    merged = merge_tick_frames(existing_ticks, new_ticks)
    tick_quality = quality_ticks(merged) if not merged.empty else {"tick_count": 0, "invalid_count": 0, "ok": False}
    bars = ticks_to_m5_coverage_bars(merged) if not merged.empty else existing_bars
    if (bars is None or bars.empty) and existing_bars is not None:
        bars = existing_bars

    tape_path = None
    raw_path = None
    tape_meta: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    if bars is not None and not bars.empty:
        fp = tape_fingerprint(bars[["bid", "ask"]])
        tape_meta = {
            "symbol": CANONICAL_SYMBOL,
            "timeframe": CANONICAL_TIMEFRAME,
            "source": "mt5_copy_ticks_range + phase27_25_merge",
            "collection_method": "merge prior valid ticks with bounded missing-interval copy_ticks_range",
            "broker": account.get("broker"),
            "server": account.get("server"),
            "row_count": int(len(bars)),
            "tick_count": int(len(merged)) if not merged.empty else 0,
            "time_range": {"start": _iso(bars.index.min()), "end": _iso(bars.index.max()), "timezone": "UTC"},
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
            (root / TAPE_META).write_text(json.dumps(_sanitize(tape_meta), indent=2, sort_keys=True), encoding="utf-8")
            tape_path = TAPE_PARQUET
            if not merged.empty:
                raw = pd.DataFrame(
                    {
                        "time_utc": pd.to_datetime(merged["time"], unit="s", utc=True),
                        "bid": pd.to_numeric(merged["bid"], errors="coerce"),
                        "ask": pd.to_numeric(merged["ask"], errors="coerce"),
                        "symbol": CANONICAL_SYMBOL,
                        "source": "phase27_26_merge",
                    }
                )
                if "flags" in merged.columns:
                    raw["flags"] = merged["flags"].to_numpy()
                if "volume" in merged.columns:
                    raw["volume"] = merged["volume"].to_numpy()
                raw.to_parquet(root / RAW_TICKS_PARQUET)
                raw_path = RAW_TICKS_PARQUET

    cmp_ = compare_coverage(dataset, bars)
    collected_through = cmp_.get("evidence_end")
    stop_reason = collect_meta.get("stop_reason")
    gaps = annotate_gaps(
        list(cmp_.get("uncovered_intervals") or []),
        collected_through=collected_through,
        stop_reason=stop_reason,
    )
    cmp_["uncovered_intervals"] = gaps
    if gaps:
        cmp_["largest_gap"] = max(gaps, key=lambda g: g.get("bars") or 0)

    classification = classify_canonical_coverage(
        covered_bars=int(cmp_["covered_M5_bars"]),
        dataset_bars=int(cmp_["dataset_M5_bars"]),
        collection_attempted=bool(collect_meta.get("attempted")) or existing_used,
    )
    if operator_dependency and not existing_used and int(cmp_["covered_M5_bars"]) == 0:
        classification = BLOCKED_PENDING_DATA
        status = "BLOCKED"

    fp_after = _file_sha256(dataset_path)
    dataset_after = pd.read_parquet(dataset_path)
    sig_after = ohlc_signature(dataset_after)
    originals_untouched, issues = verify_immutability(before_manifest, base_dir=root)
    production_changed = fp_after != fp_before or sig_after != sig_before
    tape_25_after = _file_sha256(root / PHASE2725_TAPE) if (root / PHASE2725_TAPE).is_file() else None
    tape_25_preserved = tape_25_before == tape_25_after
    if production_changed or not originals_untouched or (tape_25_before and not tape_25_preserved):
        status = "FAILED"
        errors.append("immutability_violation")

    hist = historical_spread_status(classification)
    final_gate = str((_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or "UNKNOWN")
    requested_start = min((w.get("requested_from_utc") for w in collect_meta.get("windows") or [] if w.get("requested_from_utc")), default=None)
    requested_end = max((w.get("requested_to_utc") for w in collect_meta.get("windows") or [] if w.get("requested_to_utc")), default=None)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.26",
        "status": status,
        "collection_timestamp_utc": timestamp,
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "account_type": account.get("trade_mode_label"),
        "broker": account.get("broker"),
        "server": account.get("server"),
        "terminal_build": terminal.get("build"),
        "symbol": CANONICAL_SYMBOL,
        "dataset_path": PRODUCTION_M5,
        "dataset_fingerprint_before": fp_before,
        "dataset_fingerprint_after": fp_after,
        "dataset_rows": inspected["rows"],
        "dataset_start_utc": inspected["start_utc"],
        "dataset_end_utc": inspected["end_utc"],
        "requested_start_utc": requested_start,
        "requested_end_utc": requested_end,
        "tick_count": int(tick_quality.get("tick_count") or 0),
        "invalid_tick_count": int(tick_quality.get("invalid_count") or 0),
        "evidence_start_utc": cmp_.get("evidence_start"),
        "evidence_end_utc": cmp_.get("evidence_end"),
        "covered_bar_count": cmp_.get("covered_M5_bars"),
        "total_bar_count": cmp_.get("dataset_M5_bars"),
        "coverage_percent": cmp_.get("coverage_percent"),
        "fully_covered": cmp_.get("canonical_fully_covered"),
        "uncovered_intervals": gaps,
        "largest_gap": cmp_.get("largest_gap"),
        "collection_stop_reason": stop_reason,
        "existing_evidence_used": existing_used,
        "production_parquet_changed": production_changed,
        "historical_spread_classification": hist,
        "final_classification": classification,
        "errors": errors,
        "operator_dependency": operator_dependency,
        "provenance": tape_meta,
        "canonical_dataset": inspected,
        "environment_verified": env_ok,
        "environment_reason": env_reason,
        "collection": collect_meta,
        "tick_quality": tick_quality,
        "coverage_matrix": cmp_,
        "tape": {
            "path": tape_path,
            "raw_ticks_path": raw_path,
            "phase27_25_tape_preserved": tape_25_preserved,
            "phase27_25_tape": PHASE2725_TAPE,
            "production_dataset": False,
            "validation": validation,
        },
        "ohlc_signature_before": sig_before,
        "ohlc_signature_after": sig_after,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": issues,
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
            "production_parquet_overwritten": production_changed,
            "phase27_25_tape_overwritten": bool(tape_25_before and not tape_25_preserved),
            "proxy_converted_to_dataset": False,
            "phase_27_27_started": False,
        },
        "deferred": ["Phase 27.27+ — not started"],
    }
    missing_keys = [k for k in REQUIRED_ARTIFACT_KEYS if k not in payload]
    if missing_keys:
        payload["status"] = "FAILED"
        payload["errors"] = list(payload["errors"]) + [f"missing_artifact_keys:{','.join(missing_keys)}"]

    out = root / PHASE2726_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_26_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_26_canonical_bidask_coverage(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    ds = payload.get("canonical_dataset") or {}
    md = f"""# Phase 27.26 — Complete Canonical XAUUSD_i M5 Bid/Ask Coverage

**Status:** {payload.get('status')}  
**Classification:** `{payload.get('final_classification')}`  
**historical_spread:** `{payload.get('historical_spread_classification')}`  
**Artifact:** `{PHASE2726_JSON}`  
**Collection timestamp UTC:** `{payload.get('collection_timestamp_utc')}`

Read-only. Phase 27.25 tape was not overwritten. Production parquet was not rewritten.

## Dataset

| Field | Value |
|---|---|
| path | `{payload.get('dataset_path')}` |
| symbol | `{payload.get('symbol')}` |
| timeframe | `{ds.get('timeframe')}` |
| rows | `{payload.get('dataset_rows')}` |
| start UTC | `{payload.get('dataset_start_utc')}` |
| end UTC | `{payload.get('dataset_end_utc')}` |
| fingerprint before | `{payload.get('dataset_fingerprint_before')}` |
| fingerprint after | `{payload.get('dataset_fingerprint_after')}` |

## Evidence

| Field | Value |
|---|---|
| ticks | `{payload.get('tick_count')}` |
| invalid | `{payload.get('invalid_tick_count')}` |
| evidence range | `{payload.get('evidence_start_utc')}` → `{payload.get('evidence_end_utc')}` |
| covered bars | `{payload.get('covered_bar_count')}` / `{payload.get('total_bar_count')}` |
| coverage % | `{payload.get('coverage_percent')}` |
| fully covered | `{payload.get('fully_covered')}` |
| largest gap | `{payload.get('largest_gap')}` |
| stop reason | `{payload.get('collection_stop_reason')}` |
| existing 27.25 used | `{payload.get('existing_evidence_used')}` |

## Historical spread

`{payload.get('historical_spread_classification')}`. PROXY remains on the production parquet. COMPLETE_COSTS_REQUIRED was not weakened. FINAL_GATE remains `{payload.get('phase27_16_final_gate_unchanged')}`.

## Immutability

Production parquet changed: `{payload.get('production_parquet_changed')}`.  
27.25 tape preserved: `{payload.get('tape', {}).get('phase27_25_tape_preserved')}`.

## Next

STOP after Phase 27.26.
"""
    (root / PHASE2726_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.26 canonical bid/ask coverage:** `{PHASE2726_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.25 canonical bid/ask coverage:** `logs/phase27_25_canonical_bidask_coverage.json` — classification `PARTIAL_CANONICAL_COVERAGE`; production parquet unchanged; C full coverage BLOCKED",
            "**Phase 27.25 canonical bid/ask coverage:** `logs/phase27_25_canonical_bidask_coverage.json` — classification `PARTIAL_CANONICAL_COVERAGE`; production parquet unchanged; C full coverage BLOCKED  \n"
            + pointer
            + f" — `{payload.get('final_classification')}`; historical_spread `{payload.get('historical_spread_classification')}`; production parquet unchanged",
        )
    old = (
        "| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed. "
        "Phase 27.25 `PARTIAL_CANONICAL_COVERAGE`; historical_spread `PARTIAL`; "
        "production parquet unchanged; C=BLOCKED |"
    )
    new = (
        "| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed. "
        f"Phase 27.26 `{payload.get('final_classification')}`; "
        f"historical_spread `{payload.get('historical_spread_classification')}`; "
        "production parquet unchanged |"
    )
    if old in text:
        text = text.replace(old, new)
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
