"""Phase 27.23 — expand historical XAUUSD_i M5 Bid/Ask coverage.

Read-only. Completes the truncated Phase 27.18 7-day window via bounded chunks.
Never overwrites production/research parquets. PROXY is never historical Bid/Ask.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.cost_model import SpreadMode, detect_spread_mode_from_frame, frame_has_historical_bid_ask
from tradingbot.backtest.historical_bidask import (
    CANONICAL_SYMBOL,
    CANONICAL_TIMEFRAME,
    credentials_contaminated,
    tape_fingerprint,
)
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS, ticks_to_m5_bidask_bars
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    account_identity_snapshot,
    bounded_readonly_attach_once,
    terminal_build_snapshot,
)
from tradingbot.backtest.phase27_11_historical_bidask import inventory_existing_datasets
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_18_historical_bidask import (
    EVIDENCE_BLOCKED,
    EVIDENCE_DATASET,
    PHASE2718_JSON,
    TAPE_META as PHASE2718_TAPE_META,
    TAPE_PARQUET as PHASE2718_TAPE,
    reject_substitution_sources,
    validate_phase2718_tape,
)

PHASE2723_JSON = "logs/phase27_23_bidask_expansion.json"
PHASE2723_MD = "docs_v2/01_truth/PHASE27_23_BIDASK_EXPANSION.md"
TAPE_PARQUET = "logs/phase27_23_xauusd_i_m5_bidask.parquet"
TAPE_META = "logs/phase27_23_xauusd_i_m5_bidask.metadata.json"
RAW_TICKS_PARQUET = "logs/phase27_23_xauusd_i_ticks.parquet"
PRODUCTION_M5 = "data/XAUUSD_i_5m.parquet"
PRODUCTION_H4 = "data/XAUUSD_i_4h.parquet"

REQUIRED_ENV = "REAL"
REQUIRED_SERVER = "LiteFinance-MT5-Live"
WINDOW_DAYS = 7
CHUNK_HOURS = 6
MAX_TICKS_PER_CHUNK = 100_000
MAX_CHUNKS = 40
MAX_TOTAL_TICKS = 1_200_000
MIN_SPLIT_HOURS = 1

PHASE2718_KNOWN_FINGERPRINT = "c6aedc9bca3f9cf66d2c2e2971a301e224b2157e1cf91c60933a9a742398d319"
PROVEN = "PROVEN"
BLOCKED = "BLOCKED"

PRODUCTION_PROTECTED = (
    PRODUCTION_M5,
    PRODUCTION_H4,
    "data/backtest/XAUUSD_i_5m.parquet",
)


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


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _iso(ts: datetime | pd.Timestamp | None) -> str:
    if ts is None or pd.isna(ts):
        return "UNKNOWN"
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def environment_is_required(account: dict[str, Any]) -> tuple[bool, str]:
    env = str(account.get("trade_mode_label") or "UNKNOWN")
    server = str(account.get("server") or "UNKNOWN")
    if env != REQUIRED_ENV:
        return False, f"environment {env} is not {REQUIRED_ENV}"
    if server != REQUIRED_SERVER:
        return False, f"server {server} is not {REQUIRED_SERVER}"
    return True, "ok"


def chunk_windows(date_from: datetime, date_to: datetime, hours: int) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    cursor = date_from
    step = timedelta(hours=hours)
    while cursor < date_to:
        end = min(cursor + step, date_to)
        windows.append((cursor, end))
        cursor = end
    return windows


def classify_coverage(
    *,
    tape_valid: bool,
    tape_bars: int,
    full_canonical_covered: bool,
) -> dict[str, str]:
    """A/B/C must not be conflated."""
    exists = PROVEN if tape_valid and tape_bars > 0 else BLOCKED
    bounded = PROVEN if tape_valid and tape_bars > 0 else BLOCKED
    full = PROVEN if full_canonical_covered and tape_valid else BLOCKED
    return {
        "A_historical_bid_ask_exists": exists,
        "B_bounded_validation_window": bounded,
        "C_full_canonical_dataset": full,
    }


def compare_to_canonical(tape: pd.DataFrame | None, prod: pd.DataFrame | None) -> dict[str, Any]:
    if tape is None or tape.empty or prod is None or prod.empty:
        return {
            "canonical_path": PRODUCTION_M5,
            "canonical_rows": 0 if prod is None or prod.empty else int(len(prod)),
            "overlap": False,
            "overlap_bar_count": 0,
            "canonical_fully_covered": False,
            "note": "missing tape or canonical dataset",
        }
    tape_idx = pd.to_datetime(tape.index, utc=True)
    prod_idx = pd.to_datetime(prod.index, utc=True)
    tape_start, tape_end = tape_idx.min(), tape_idx.max()
    prod_start, prod_end = prod_idx.min(), prod_idx.max()
    overlap_start = max(tape_start, prod_start)
    overlap_end = min(tape_end, prod_end)
    has_overlap = bool(overlap_start <= overlap_end)
    overlap_bars = int(((prod_idx >= tape_start) & (prod_idx <= tape_end)).sum()) if has_overlap else 0
    exact = 0
    if has_overlap:
        exact = int(len(prod_idx.intersection(tape_idx)))
    full = bool(tape_start <= prod_start and tape_end >= prod_end)
    return {
        "canonical_path": PRODUCTION_M5,
        "canonical_rows": int(len(prod)),
        "canonical_start_utc": _iso(prod_start),
        "canonical_end_utc": _iso(prod_end),
        "canonical_duration_hours": round((prod_end - prod_start).total_seconds() / 3600.0, 3),
        "tape_start_utc": _iso(tape_start),
        "tape_end_utc": _iso(tape_end),
        "overlap": has_overlap,
        "overlap_start_utc": _iso(overlap_start) if has_overlap else None,
        "overlap_end_utc": _iso(overlap_end) if has_overlap else None,
        "overlap_bar_count": overlap_bars,
        "exact_timestamp_matches": exact,
        "canonical_coverage_ratio": round(overlap_bars / len(prod), 6) if len(prod) else 0.0,
        "canonical_fully_covered": full,
    }


def quality_ticks(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        return {
            "tick_count": 0,
            "invalid_count": 0,
            "bid_nonpositive": 0,
            "ask_nonpositive": 0,
            "ask_lt_bid": 0,
            "ok": False,
        }
    bid = pd.to_numeric(df["bid"], errors="coerce") if "bid" in df.columns else pd.Series(dtype=float)
    ask = pd.to_numeric(df["ask"], errors="coerce") if "ask" in df.columns else pd.Series(dtype=float)
    bid_bad = int((~(bid > 0)).sum()) if len(bid) else int(len(df))
    ask_bad = int((~(ask > 0)).sum()) if len(ask) else int(len(df))
    order_bad = int((ask < bid).sum()) if len(bid) and len(ask) else 0
    invalid = int(((~(bid > 0)) | (~(ask > 0)) | (ask < bid)).sum()) if len(bid) and len(ask) else int(len(df))
    return {
        "tick_count": int(len(df)),
        "invalid_count": invalid,
        "bid_nonpositive": bid_bad,
        "ask_nonpositive": ask_bad,
        "ask_lt_bid": order_bad,
        "ok": invalid == 0 and int(len(df)) > 0,
    }


def _copy_ticks_chunk(symbol: str, date_from: datetime, date_to: datetime) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    meta: dict[str, Any] = {
        "symbol": symbol,
        "method": "copy_ticks_range read-only",
        "date_from_utc": _iso(date_from),
        "date_to_utc": _iso(date_to),
        "ok": False,
        "row_count": 0,
    }
    try:
        import MetaTrader5 as mt5
    except ImportError:
        meta["error"] = "MetaTrader5 package not installed"
        return None, meta
    try:
        ticks = mt5.copy_ticks_range(symbol, date_from, date_to, mt5.COPY_TICKS_ALL)
    except Exception as exc:
        meta["error"] = str(exc)
        return None, meta
    if ticks is None or len(ticks) == 0:
        meta["ok"] = True
        meta["empty"] = True
        return pd.DataFrame(), meta
    df = pd.DataFrame(ticks)
    meta["ok"] = True
    meta["row_count"] = int(len(df))
    meta["columns"] = [str(c) for c in df.columns]
    return df, meta


def collect_ticks_chunked(symbol: str, date_from: datetime, date_to: datetime) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    pending = chunk_windows(date_from, date_to, CHUNK_HOURS)
    frames: list[pd.DataFrame] = []
    chunk_log: list[dict[str, Any]] = []
    total = 0
    calls = 0
    truncated_chunks = 0
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
        if df is not None and not df.empty:
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
    return combined if not combined.empty else (combined if frames else None), {
        "ok": not combined.empty,
        "method": "copy_ticks_range bounded 6-hour chunks; split if cap hit; no symbol_select",
        "window_days": WINDOW_DAYS,
        "chunk_hours": CHUNK_HOURS,
        "max_ticks_per_chunk": MAX_TICKS_PER_CHUNK,
        "max_chunks": MAX_CHUNKS,
        "max_total_ticks": MAX_TOTAL_TICKS,
        "chunk_calls": calls,
        "chunks_logged": len(chunk_log),
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


def load_phase2718_baseline(root: Path) -> dict[str, Any]:
    meta = _safe_load_json(root / PHASE2718_TAPE_META)
    payload = _safe_load_json(root / PHASE2718_JSON)
    tr = meta.get("time_range") if isinstance(meta.get("time_range"), dict) else {}
    return {
        "artifact": PHASE2718_JSON,
        "tape_path": PHASE2718_TAPE,
        "exists": (root / PHASE2718_TAPE).is_file(),
        "bars": int(meta.get("row_count") or 82),
        "start_utc": tr.get("start") or "2026-09-04T17:10:00Z",
        "end_utc": tr.get("end") or "2026-09-04T23:55:00Z",
        "fingerprint": meta.get("fingerprint") or PHASE2718_KNOWN_FINGERPRINT,
        "evidence_status": payload.get("evidence_status"),
    }


def materially_improved(baseline: dict[str, Any], bars: int, start: str, end: str) -> dict[str, Any]:
    try:
        base_start = pd.Timestamp(baseline["start_utc"])
        base_end = pd.Timestamp(baseline["end_utc"])
        new_start = pd.Timestamp(start)
        new_end = pd.Timestamp(end)
        base_hours = (base_end - base_start).total_seconds() / 3600.0
        new_hours = (new_end - new_start).total_seconds() / 3600.0
    except (TypeError, ValueError):
        base_hours = 0.0
        new_hours = 0.0
    improved = bool(bars > int(baseline["bars"]) or new_hours > base_hours + 0.01)
    return {
        "improved": improved,
        "baseline_bars": int(baseline["bars"]),
        "new_bars": bars,
        "baseline_hours": round(base_hours, 3),
        "new_hours": round(new_hours, 3),
        "earlier_start": start < str(baseline["start_utc"]),
        "later_end": end > str(baseline["end_utc"]),
    }


def run_phase27_23_bidask_expansion(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    before = build_immutability_manifest(root)
    baseline = load_phase2718_baseline(root)
    inventory = inventory_existing_datasets(root)
    attach = bounded_readonly_attach_once()
    account = {
        "trade_mode_label": "UNKNOWN",
        "server": "UNKNOWN",
        "broker": "UNKNOWN",
    }
    terminal = {"build": "UNKNOWN", "connected": False}
    tape_status = EVIDENCE_BLOCKED
    tape_path = None
    raw_path = None
    tape_meta: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    tick_quality: dict[str, Any] = {}
    collect_meta: dict[str, Any] = {
        "attempted": False,
        "method": "copy_ticks_range bounded chunks; no symbol_select; no current-tick substitution",
        "window_days": WINDOW_DAYS,
    }
    env_ok = False
    env_reason = "not_attached"
    bars: pd.DataFrame | None = None

    if attach.get("ok"):
        import MetaTrader5 as mt5

        account = account_identity_snapshot(mt5)
        terminal = terminal_build_snapshot(mt5)
        env_ok, env_reason = environment_is_required(account)
        if env_ok:
            info = mt5.symbol_info(CANONICAL_SYMBOL)
            if info is None:
                collect_meta["error"] = f"{CANONICAL_SYMBOL} not visible via symbol_info (symbol_select not called)"
            else:
                collect_meta["attempted"] = True
                date_to = datetime.now(timezone.utc)
                date_from = date_to - timedelta(days=WINDOW_DAYS)
                ticks, tick_meta = collect_ticks_chunked(CANONICAL_SYMBOL, date_from, date_to)
                collect_meta.update(tick_meta)
                if ticks is not None and not ticks.empty:
                    tick_quality = quality_ticks(ticks)
                    valid_mask = (
                        (pd.to_numeric(ticks["bid"], errors="coerce") > 0)
                        & (pd.to_numeric(ticks["ask"], errors="coerce") > 0)
                        & (pd.to_numeric(ticks["ask"], errors="coerce") >= pd.to_numeric(ticks["bid"], errors="coerce"))
                    )
                    clean = ticks.loc[valid_mask].copy()
                    bars = ticks_to_m5_bidask_bars(clean)
                    if bars is not None and not bars.empty and frame_has_historical_bid_ask(bars):
                        if getattr(bars.index, "tz", None) is None:
                            bars.index = pd.to_datetime(bars.index, utc=True)
                        fp = tape_fingerprint(bars)
                        start = bars.index[0]
                        end = bars.index[-1]
                        tape_meta = {
                            "symbol": CANONICAL_SYMBOL,
                            "timeframe": CANONICAL_TIMEFRAME,
                            "source": "mt5_copy_ticks_range",
                            "collection_method": "copy_ticks_range bounded 6-hour chunks; no symbol_select",
                            "broker": account.get("broker"),
                            "server": account.get("server"),
                            "row_count": int(len(bars)),
                            "tick_count": int(len(clean)),
                            "time_range": {
                                "start": _iso(start),
                                "end": _iso(end),
                                "timezone": "UTC",
                            },
                            "fingerprint": fp,
                            "utc_timestamp": timestamp,
                            "current_bid_ask_tick": False,
                            "ohlc_spread": False,
                            "proxy_spread": False,
                            "evidence_scope": "bounded_logs_only_validation_window",
                            "not_a_production_dataset": True,
                        }
                        validation = validate_phase2718_tape(
                            bars,
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
                            raw = _raw_tick_frame(clean, account)
                            raw.to_parquet(root / RAW_TICKS_PARQUET)
                            raw_path = RAW_TICKS_PARQUET
                            tape_path = TAPE_PARQUET
                            tape_status = EVIDENCE_DATASET
                        else:
                            tape_status = EVIDENCE_BLOCKED
                            collect_meta["error"] = validation.get("errors") or "validation_failed"
                    else:
                        tape_status = EVIDENCE_BLOCKED
                        collect_meta["error"] = "tick aggregation produced no historical bid/ask M5 bars"
                else:
                    tape_status = EVIDENCE_BLOCKED
                    collect_meta["error"] = tick_meta.get("error") or "no historical ticks returned"
        else:
            tape_status = EVIDENCE_BLOCKED
            collect_meta["collection_possible"] = False
            collect_meta["error"] = env_reason
    else:
        collect_meta["collection_possible"] = False
        collect_meta["error"] = attach.get("error") or "MT5 not attached"
        tape_status = EVIDENCE_BLOCKED

    originals_untouched, immutability_issues = verify_immutability(before, base_dir=root)
    protected_untouched = _protected_files_untouched(root, before)
    prod = _load_production_m5(root)
    coverage_cmp = compare_to_canonical(bars, prod)
    tape_valid = tape_status == EVIDENCE_DATASET and bars is not None and not bars.empty
    tape_bars = int(len(bars)) if bars is not None and not bars.empty else 0
    prior_valid = bool(baseline.get("exists")) and int(baseline.get("bars") or 0) > 0
    coverage = classify_coverage(
        tape_valid=tape_valid or prior_valid,
        tape_bars=tape_bars if tape_valid else int(baseline.get("bars") or 0),
        full_canonical_covered=bool(coverage_cmp.get("canonical_fully_covered")),
    )
    start_utc = tape_meta.get("time_range", {}).get("start") if tape_meta else None
    end_utc = tape_meta.get("time_range", {}).get("end") if tape_meta else None
    duration_hours = 0.0
    if start_utc and end_utc:
        duration_hours = round(
            (pd.Timestamp(end_utc) - pd.Timestamp(start_utc)).total_seconds() / 3600.0, 3
        )
    improvement = materially_improved(
        baseline,
        tape_bars,
        start_utc or baseline["start_utc"],
        end_utc or baseline["end_utc"],
    )
    if not tape_valid:
        improvement = {**improvement, "improved": False, "new_bars": 0, "new_hours": 0.0}

    final_gate = str((_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or "UNKNOWN")
    ohlc_probe = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.1], "volume": [1]})

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.23",
        "status": "PASS" if originals_untouched and protected_untouched else "FAIL",
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "canonical_symbol": CANONICAL_SYMBOL,
        "canonical_timeframe": CANONICAL_TIMEFRAME,
        "required_environment": {"env": REQUIRED_ENV, "server": REQUIRED_SERVER},
        "environment_verified": env_ok,
        "environment_reason": env_reason,
        "mt5_attach": {
            "ok": attach.get("ok"),
            "error": attach.get("error"),
            "environment": account.get("trade_mode_label"),
            "server": account.get("server"),
            "broker": account.get("broker"),
            "started": False,
            "restarted": False,
        },
        "account": _sanitize(account),
        "terminal": terminal,
        "phase27_18_baseline": baseline,
        "collection": collect_meta,
        "tick_quality": tick_quality,
        "tape": {
            "path": tape_path,
            "raw_ticks_path": raw_path,
            "status": tape_status,
            "provenance": tape_meta,
            "validation": validation,
            "production_dataset": False,
            "tick_count": tick_quality.get("tick_count") or collect_meta.get("tick_count") or 0,
            "m5_bar_count": tape_bars,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "coverage_duration_hours": duration_hours,
            "missing_invalid_ticks": tick_quality.get("invalid_count", 0),
            "fingerprint": tape_meta.get("fingerprint"),
        },
        "coverage": coverage,
        "canonical_comparison": coverage_cmp,
        "materially_improved_vs_27_18": improvement,
        "spread_dataset_for_bounded_logs_window": coverage["B_bounded_validation_window"] == PROVEN,
        "spread_dataset_for_production_parquet": False,
        "canonical_dataset_fully_covered": bool(coverage_cmp.get("canonical_fully_covered")),
        "full_cost_aware_validation_blocked": True,
        "proxy_not_substituted": True,
        "substitutions_rejected": reject_substitution_sources(),
        "inventory": {
            "production_historical_bid_ask": bool(inventory.get("historical_bid_ask_available")),
            "production_spread_mode": SpreadMode.PROXY.value
            if not inventory.get("historical_bid_ask_available")
            else SpreadMode.DATASET.value,
        },
        "ohlc_frame_spread_mode": detect_spread_mode_from_frame(ohlc_probe).value,
        "original_datasets_untouched": originals_untouched,
        "protected_production_untouched": protected_untouched,
        "immutability_issues": immutability_issues,
        "phase27_16_final_gate_unchanged": final_gate,
        "complete_costs_required_weakened": False,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "mt5_restarted": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "account_state_modified": False,
            "env_file_read": False,
            "env_file_written": False,
            "original_datasets_overwritten": not originals_untouched,
            "production_parquet_overwritten": not protected_untouched,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "proxy_used_as_historical": False,
            "phase_27_24_started": False,
        },
        "deferred": ["Phase 27.24+ — not started"],
    }
    if tape_status not in (EVIDENCE_DATASET, EVIDENCE_BLOCKED):
        payload["status"] = "FAIL"
    if not originals_untouched or not protected_untouched:
        payload["status"] = "FAIL"
    if credentials_contaminated(payload):
        payload["status"] = "FAIL"

    out = root / PHASE2723_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_23_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_23_bidask_expansion(base_dir)


def _raw_tick_frame(ticks: pd.DataFrame, account: dict[str, Any]) -> pd.DataFrame:
    out = pd.DataFrame()
    if "time" in ticks.columns:
        out["time_utc"] = pd.to_datetime(ticks["time"], unit="s", utc=True)
    elif "time_msc" in ticks.columns:
        out["time_utc"] = pd.to_datetime(ticks["time_msc"], unit="ms", utc=True)
    out["bid"] = pd.to_numeric(ticks["bid"], errors="coerce")
    out["ask"] = pd.to_numeric(ticks["ask"], errors="coerce")
    if "flags" in ticks.columns:
        out["flags"] = ticks["flags"]
    out["symbol"] = CANONICAL_SYMBOL
    out["source"] = "mt5_copy_ticks_range"
    out["broker"] = account.get("broker")
    out["server"] = account.get("server")
    out["collection_method"] = "copy_ticks_range bounded chunks"
    return out.reset_index(drop=True)


def _load_production_m5(root: Path) -> pd.DataFrame | None:
    path = root / PRODUCTION_M5
    if not path.is_file():
        return None
    try:
        df = pd.read_parquet(path)
    except (OSError, ValueError):
        return None
    if not isinstance(df.index, pd.DatetimeIndex):
        return df
    if df.index.tz is None:
        df = df.copy()
        df.index = pd.to_datetime(df.index, utc=True)
    return df


def _protected_files_untouched(root: Path, before: dict[str, Any]) -> bool:
    before_ds = before.get("datasets") or {}
    for rel in PRODUCTION_PROTECTED:
        path = root / rel
        name = path.name
        if name in before_ds and path.is_file():
            continue
        if path.is_file() and name in ("XAUUSD_i_5m.parquet", "XAUUSD_i_4h.parquet"):
            continue
    after = build_immutability_manifest(root)
    after_ds = after.get("datasets") or {}
    for rel in (PRODUCTION_M5, PRODUCTION_H4):
        name = Path(rel).name
        if name in before_ds and name in after_ds:
            if after_ds[name].get("sha256") != before_ds[name].get("sha256"):
                return False
    return True


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    tape = payload["tape"]
    cov = payload["coverage"]
    cmp_ = payload["canonical_comparison"]
    base = payload["phase27_18_baseline"]
    imp = payload["materially_improved_vs_27_18"]
    md = f"""# Phase 27.23 — Historical XAUUSD_i M5 Bid/Ask Coverage Expansion

**Status:** {payload['status']}  
**This-session tape:** `{tape['status']}`  
**Artifact:** `{PHASE2723_JSON}`  
**Collection timestamp UTC:** `{payload['timestamp']}`

Read-only. No MT5 start/restart, orders, `symbol_select`, `.env`, or production parquet overwrite.

## Environment

Verified REAL / `{REQUIRED_SERVER}`: **{payload['environment_verified']}** (`{payload['environment_reason']}`).  
Attach: `{payload['mt5_attach'].get('environment')}` / `{payload['mt5_attach'].get('server')}`.  
Terminal build: `{payload['terminal'].get('build')}`.

## Collection

Bounded 7-day UTC window via 6-hour `copy_ticks_range` chunks (split if a chunk hits {MAX_TICKS_PER_CHUNK} ticks). Not an unbounded download.

| Metric | Value |
|---|---|
| ticks | `{tape['tick_count']}` |
| invalid ticks | `{tape['missing_invalid_ticks']}` |
| M5 bars | `{tape['m5_bar_count']}` |
| start UTC | `{tape['start_utc']}` |
| end UTC | `{tape['end_utc']}` |
| duration hours | `{tape['coverage_duration_hours']}` |
| fingerprint | `{tape['fingerprint']}` |
| M5 tape | `{tape['path']}` |
| raw ticks | `{tape['raw_ticks_path']}` |

## vs Phase 27.18

27.18: `{base['bars']}` bars, `{base['start_utc']}` → `{base['end_utc']}`, fingerprint `{base['fingerprint']}`.

Materially improved: **{imp.get('improved')}** ({imp.get('new_bars')} bars / {imp.get('new_hours')} h vs {imp.get('baseline_bars')} / {imp.get('baseline_hours')} h).

Safety stop: `{payload['collection'].get('stop_reason')}`. Requested window `{payload['collection'].get('requested_from_utc')}` → `{payload['collection'].get('requested_to_utc')}`. This tape is not automatically a superset of Phase 27.18.

## Coverage vs `data/XAUUSD_i_5m.parquet`

Canonical range: `{cmp_.get('canonical_start_utc')}` → `{cmp_.get('canonical_end_utc')}` (`{cmp_.get('canonical_rows')}` bars).  
Overlap: **{cmp_.get('overlap')}**. Exact timestamp matches: `{cmp_.get('exact_timestamp_matches')}`.  
Full canonical coverage: **{cmp_.get('canonical_fully_covered')}**.

| Class | Result |
|---|---|
| A. Historical Bid/Ask exists | **{cov['A_historical_bid_ask_exists']}** |
| B. Bounded validation window | **{cov['B_bounded_validation_window']}** |
| C. Full canonical research dataset | **{cov['C_full_canonical_dataset']}** |

Spread may be **DATASET** only for the logs-only bounded window (`{payload['spread_dataset_for_bounded_logs_window']}`).  
Production parquet spread remains PROXY (`{payload['spread_dataset_for_production_parquet']}`).  
Full cost-aware validation remains **BLOCKED**.

PROXY / OHLC / live tick were not substituted.

## Production

**BLOCKED.** COMPLETE_COSTS_REQUIRED was not weakened. FINAL_GATE remains `{payload['phase27_16_final_gate_unchanged']}`.  
`{PRODUCTION_M5}` and `{PRODUCTION_H4}` were not overwritten. Phase 27.24+ not started.

## Next

STOP after Phase 27.23.
"""
    (root / PHASE2723_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        pointer = f"**Phase 27.23 bid/ask expansion:** `{PHASE2723_JSON}`"
        if pointer not in text:
            text = text.replace(
                "**Phase 27.22 commission forensic:** `logs/phase27_22_commission_forensic.json` — account_product_type UNKNOWN; classification remains OBSERVED_ZERO_NOT_PROVEN",
                "**Phase 27.22 commission forensic:** `logs/phase27_22_commission_forensic.json` — account_product_type UNKNOWN; classification remains OBSERVED_ZERO_NOT_PROVEN  \n"
                + pointer
                + " — logs tape expanded; production parquet still PROXY; C full-dataset coverage BLOCKED",
            )
        old = (
            "| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed. "
            "Phase 27.18 production `BLOCKED_PENDING_DATA`; logs tape `DATASET` |"
        )
        new = (
            "| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed. "
            f"Phase 27.23 production still PROXY; logs tape `{payload['tape']['status']}`; "
            f"A={payload['coverage']['A_historical_bid_ask_exists']} "
            f"B={payload['coverage']['B_bounded_validation_window']} "
            f"C={payload['coverage']['C_full_canonical_dataset']} |"
        )
        if old in text:
            text = text.replace(old, new)
        if text != path.read_text(encoding="utf-8"):
            path.write_text(text, encoding="utf-8")
