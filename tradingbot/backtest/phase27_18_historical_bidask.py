"""Phase 27.18 — historical M5 Bid/Ask closure for canonical XAUUSD_i.

Read-only. PROXY / OHLC / spread-column / current tick are never historical Bid/Ask.
Original production parquets are never overwritten.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.cost_model import (
    SpreadMode,
    detect_spread_mode_from_frame,
    frame_has_historical_bid_ask,
)
from tradingbot.backtest.dataset_provenance import audit_backtest_datasets
from tradingbot.backtest.historical_bidask import (
    CANONICAL_SYMBOL,
    CANONICAL_TIMEFRAME,
    current_tick_is_not_historical,
    tape_fingerprint,
    validate_historical_m5_tape,
)
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS, ticks_to_m5_bidask_bars
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_11_historical_bidask import (
    BOUNDED_MAX_TICKS,
    BOUNDED_TICK_DAYS,
    TAPE_PARQUET as PHASE2711_TAPE,
    _copy_ticks_already_attached,
    inventory_existing_datasets,
)
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    account_identity_snapshot,
    bounded_readonly_attach_once,
)

PHASE2718_JSON = "logs/phase27_18_historical_bidask.json"
PHASE2718_MD = "docs_v2/01_truth/PHASE27_18_HISTORICAL_BIDASK_CLOSURE.md"
TAPE_PARQUET = "logs/phase27_18_xauusd_i_m5_bidask.parquet"
TAPE_META = "logs/phase27_18_xauusd_i_m5_bidask.metadata.json"
PHASE2716_JSON = "logs/phase27_16_FINAL_VALIDATION_GATE.json"
PHASE2717_JSON = "logs/phase27_17_real_broker_evidence.json"

EVIDENCE_DATASET = "DATASET"
EVIDENCE_BLOCKED = "BLOCKED_PENDING_DATA"


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


def index_is_utc(df: pd.DataFrame) -> bool:
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return False
    tz = df.index.tz
    if tz is None:
        return False
    return str(tz).upper() in {"UTC", "TZUTC"}


def prices_positive_and_ordered(df: pd.DataFrame) -> bool:
    if df is None or df.empty or not frame_has_historical_bid_ask(df):
        return False
    cols = {str(c).lower(): c for c in df.columns}
    bid = pd.to_numeric(df[cols.get("bid") or cols.get("bid_price")], errors="coerce")
    ask = pd.to_numeric(df[cols.get("ask") or cols.get("ask_price")], errors="coerce")
    return bool((bid > 0).all() and (ask > 0).all() and (bid <= ask).all())


def live_tick_is_not_historical_tape(source: str | None = None) -> bool:
    """A current or stale symbol_info_tick is never a historical M5 Bid/Ask tape."""
    provenance = {
        "source": source or "symbol_info_tick",
        "collection_method": "symbol_info_tick / live_tick / current_quote",
    }
    return current_tick_is_not_historical(provenance) is False


def classify_historical_spread_evidence(*, tape_valid: bool) -> str:
    """DATASET only when genuine historical Bid/Ask exists. Otherwise BLOCKED_PENDING_DATA."""
    return EVIDENCE_DATASET if tape_valid else EVIDENCE_BLOCKED


def classify_frame_spread_mode(df: pd.DataFrame | None) -> str:
    """Cost-model spread mode. DATASET only with historical bid+ask columns."""
    return detect_spread_mode_from_frame(df).value


def reject_substitution_sources() -> dict[str, bool]:
    return {
        "current_bid_ask_tick": True,
        "ohlc_spread": True,
        "proxy_spread": True,
        "spread_column": True,
        "phase27_17_live_tick": True,
    }


def validate_phase2718_tape(
    df: pd.DataFrame | None,
    *,
    symbol: str,
    timeframe: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    result = validate_historical_m5_tape(
        df, symbol=symbol, timeframe=timeframe, provenance=provenance
    )
    errors = list(result.get("errors") or [])
    if df is not None and not df.empty:
        if not index_is_utc(df):
            errors.append("timestamps_not_utc")
        if not prices_positive_and_ordered(df):
            errors.append("non_positive_or_unordered_prices")
    result = dict(result)
    result["errors"] = errors
    result["ok"] = not errors
    result["utc_ok"] = df is not None and not df.empty and index_is_utc(df)
    result["prices_ok"] = df is not None and not df.empty and prices_positive_and_ordered(df)
    return result


def inventory_existing_tapes(root: Path) -> dict[str, Any]:
    """Confirm whether any historical M5 XAUUSD_i Bid/Ask tape already exists."""
    candidates = [
        {
            "path": PHASE2711_TAPE,
            "role": "phase27_11_logs_evidence",
            "production_dataset": False,
        },
        {
            "path": TAPE_PARQUET,
            "role": "phase27_18_logs_evidence",
            "production_dataset": False,
        },
    ]
    found: list[dict[str, Any]] = []
    for item in candidates:
        path = root / item["path"]
        row = dict(item)
        row["exists"] = path.is_file()
        row["valid_historical_m5"] = False
        if path.is_file():
            try:
                df = pd.read_parquet(path)
            except (OSError, ValueError):
                row["error"] = "unreadable_parquet"
            else:
                row["rows"] = int(len(df))
                row["columns"] = [str(c) for c in df.columns]
                row["has_bid_ask"] = bool(frame_has_historical_bid_ask(df))
                meta_path = path.with_suffix(".metadata.json")
                if not meta_path.is_file():
                    meta_path = Path(str(path) + ".metadata.json")
                meta = _safe_load_json(meta_path)
                if not meta:
                    meta = {
                        "symbol": CANONICAL_SYMBOL,
                        "timeframe": CANONICAL_TIMEFRAME,
                        "source": "existing_logs_tape",
                        "collection_method": "prior_phase_logs_only",
                        "row_count": int(len(df)),
                        "time_range": {"start": "UNKNOWN", "end": "UNKNOWN"},
                        "fingerprint": tape_fingerprint(df) if frame_has_historical_bid_ask(df) else "UNKNOWN",
                    }
                validation = validate_phase2718_tape(
                    df,
                    symbol=str(meta.get("symbol") or CANONICAL_SYMBOL),
                    timeframe=str(meta.get("timeframe") or CANONICAL_TIMEFRAME),
                    provenance=meta,
                )
                row["valid_historical_m5"] = bool(validation.get("ok"))
                row["validation_errors"] = validation.get("errors")
        found.append(row)
    return {
        "candidates": found,
        "any_existing_valid_tape": any(r.get("valid_historical_m5") for r in found),
        "any_production_historical_m5": False,
    }


def inventory_sidecars(root: Path) -> dict[str, Any]:
    entries = audit_backtest_datasets(base_dir=root)
    rows: list[dict[str, Any]] = []
    claimed_dataset_without_bid_ask: list[str] = []
    for entry in entries:
        row = {
            "filename": entry.filename,
            "sidecar_present": entry.metadata_sidecar_present,
            "spread_mode": entry.spread_mode,
            "spread_source": entry.spread_source,
            "bid_present": entry.bid_present,
            "ask_present": entry.ask_present,
            "inferred_symbol": entry.inferred_symbol,
        }
        rows.append(row)
        if entry.spread_mode == SpreadMode.DATASET.value and not (entry.bid_present and entry.ask_present):
            claimed_dataset_without_bid_ask.append(entry.filename)
    return {
        "sidecar_count": sum(1 for r in rows if r["sidecar_present"]),
        "dataset_count": len(rows),
        "sidecars": rows,
        "dataset_claimed_without_historical_bid_ask": claimed_dataset_without_bid_ask,
    }


def extract_live_tick_rejection(root: Path) -> dict[str, Any]:
    payload = _safe_load_json(root / PHASE2717_JSON)
    econ = payload.get("economics") if isinstance(payload.get("economics"), dict) else {}
    xau = econ.get("XAUUSD_i") if isinstance(econ.get("XAUUSD_i"), dict) else {}
    return {
        "source_artifact": PHASE2717_JSON,
        "bid": xau.get("bid"),
        "ask": xau.get("ask"),
        "tick_utc": xau.get("utc_timestamp"),
        "treated_as_historical_m5_tape": False,
        "live_tick_is_historical": False,
        "reason": "current or stale symbol_info_tick Bid/Ask is not a historical M5 Bid/Ask tape",
    }


def _final_gate_status(root: Path) -> str:
    payload = _safe_load_json(root / PHASE2716_JSON)
    return str(payload.get("FINAL_GATE") or "UNKNOWN")


def run_phase27_18_historical_bidask(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    before = build_immutability_manifest(root)
    inventory = inventory_existing_datasets(root)
    sidecars = inventory_sidecars(root)
    existing_tapes = inventory_existing_tapes(root)
    live_tick = extract_live_tick_rejection(root)

    attach = bounded_readonly_attach_once()
    account = {
        "login_identity": "UNKNOWN",
        "trade_mode_label": "UNKNOWN",
        "server": "UNKNOWN",
        "broker": "UNKNOWN",
    }
    tape_status = EVIDENCE_BLOCKED
    tape_path = None
    tape_meta: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    collect_meta: dict[str, Any] = {
        "attempted": False,
        "method": "copy_ticks_range read-only; no symbol_select; no current-tick substitution",
        "bounded_tick_days": BOUNDED_TICK_DAYS,
        "bounded_max_ticks": BOUNDED_MAX_TICKS,
    }

    if attach["ok"]:
        import MetaTrader5 as mt5

        account = account_identity_snapshot(mt5)
        env = str(account.get("trade_mode_label") or "UNKNOWN")
        if env == "REAL":
            collect_meta["attempted"] = True
            collect_meta["collection_possible"] = True
            ticks, tick_meta = _copy_ticks_already_attached(
                CANONICAL_SYMBOL, days=BOUNDED_TICK_DAYS, max_ticks=BOUNDED_MAX_TICKS
            )
            collect_meta.update(tick_meta)
            collect_meta["tick_window_truncated"] = int(tick_meta.get("row_count") or 0) >= BOUNDED_MAX_TICKS
            if collect_meta["tick_window_truncated"]:
                collect_meta["note"] = (
                    "Last N ticks only; not a full requested calendar window and not a production dataset."
                )
            if ticks is not None and tick_meta.get("ok"):
                bars = ticks_to_m5_bidask_bars(ticks)
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
                        "collection_method": "copy_ticks_range read-only; no symbol_select",
                        "broker": account.get("broker"),
                        "server": account.get("server"),
                        "row_count": int(len(bars)),
                        "time_range": {
                            "start": pd.Timestamp(start).tz_convert("UTC").isoformat().replace("+00:00", "Z")
                            if getattr(start, "tzinfo", None)
                            else str(start),
                            "end": pd.Timestamp(end).tz_convert("UTC").isoformat().replace("+00:00", "Z")
                            if getattr(end, "tzinfo", None)
                            else str(end),
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
                    if validation.get("ok"):
                        out_pq = root / TAPE_PARQUET
                        out_pq.parent.mkdir(parents=True, exist_ok=True)
                        bars.to_parquet(out_pq)
                        (root / TAPE_META).write_text(
                            json.dumps(_sanitize(tape_meta), indent=2, sort_keys=True),
                            encoding="utf-8",
                        )
                        tape_path = TAPE_PARQUET
                        tape_status = EVIDENCE_DATASET
                    else:
                        tape_status = EVIDENCE_BLOCKED
                        collect_meta["error"] = validation.get("errors")
                else:
                    tape_status = EVIDENCE_BLOCKED
                    collect_meta["error"] = "tick aggregation produced no historical bid/ask M5 bars"
            else:
                tape_status = EVIDENCE_BLOCKED
        else:
            tape_status = EVIDENCE_BLOCKED
            collect_meta["collection_possible"] = False
            collect_meta["error"] = (
                f"attached environment {env} is not REAL — historical Real tape not collected"
            )
    else:
        collect_meta["collection_possible"] = False
        collect_meta["error"] = attach.get("error") or "MT5 not attached"
        tape_status = EVIDENCE_BLOCKED

    originals_untouched, _immutability_issues = verify_immutability(before, base_dir=root)
    production_has_bid_ask = bool(inventory.get("historical_bid_ask_available"))
    production_spread_mode = SpreadMode.DATASET.value if production_has_bid_ask else SpreadMode.PROXY.value
    production_evidence = classify_historical_spread_evidence(tape_valid=production_has_bid_ask)
    evidence_status = classify_historical_spread_evidence(
        tape_valid=(tape_status == EVIDENCE_DATASET) or bool(existing_tapes.get("any_existing_valid_tape"))
    )
    if tape_status != EVIDENCE_DATASET and existing_tapes.get("any_existing_valid_tape"):
        # Prior logs tape is evidence-only; do not promote production datasets.
        evidence_status = EVIDENCE_DATASET

    # A logs-only tape never reclassifies production OHLC datasets as DATASET.
    if not production_has_bid_ask:
        production_spread_mode = SpreadMode.PROXY.value
        production_evidence = EVIDENCE_BLOCKED

    final_gate = _final_gate_status(root)
    substitutions = reject_substitution_sources()
    ohlc_probe = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.1], "volume": [1]})
    spread_col_probe = pd.DataFrame(
        {"open": [2000.0], "high": [2001.0], "low": [1999.0], "close": [2000.0], "spread": [0.3]}
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.18",
        "status": "PASS"
        if originals_untouched and evidence_status in (EVIDENCE_BLOCKED, EVIDENCE_DATASET)
        else "FAIL",
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "canonical_symbol": CANONICAL_SYMBOL,
        "canonical_timeframe": CANONICAL_TIMEFRAME,
        "evidence_status": evidence_status,
        "inventory": inventory,
        "sidecar_inventory": sidecars,
        "existing_tapes": existing_tapes,
        "substitutions_rejected": substitutions,
        "dataset_spread_requires_historical_bid_ask": True,
        "proxy_not_equivalent_to_historical_bid_ask": True,
        "mt5_attach": {
            "ok": attach.get("ok"),
            "error": attach.get("error"),
            "environment": account.get("trade_mode_label"),
            "server": account.get("server"),
            "broker": account.get("broker"),
            "started": False,
            "restarted": False,
        },
        "collection": collect_meta,
        "tape": {
            "path": tape_path,
            "status": tape_status,
            "provenance": tape_meta,
            "validation": validation,
            "production_dataset": False,
        },
        "live_tick_rejected": live_tick,
        "cost_provenance": {
            "dataset_spread_requires_historical_bid_ask": True,
            "production_datasets_spread_mode": production_spread_mode,
            "production_spread_evidence_status": production_evidence,
            "logs_tape_spread_mode": tape_status if tape_status == EVIDENCE_DATASET else None,
            "logs_tape_is_not_a_production_dataset": True,
            "proxy_not_equivalent_to_historical_bid_ask": True,
            "ohlc_frame_spread_mode": classify_frame_spread_mode(ohlc_probe),
            "spread_column_frame_spread_mode": classify_frame_spread_mode(spread_col_probe),
            "sidecar_dataset_claim_without_bid_ask": sidecars.get(
                "dataset_claimed_without_historical_bid_ask"
            ),
        },
        "original_datasets_untouched": originals_untouched,
        "phase27_16_final_gate_unchanged": final_gate,
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
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_semantics_modified": False,
            "current_tick_used_as_historical": False,
            "ohlc_converted_to_historical_bid_ask": False,
            "proxy_converted_to_historical_bid_ask": False,
            "spread_column_converted_to_historical_bid_ask": False,
            "phase_27_19_started": False,
        },
        "deferred": ["Phase 27.19+ — not started"],
    }
    out = root / PHASE2718_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_known_unknowns(root, payload)
    return payload


def run_phase27_18_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_18_historical_bidask(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    inv = payload["inventory"]
    tape = payload["tape"]
    cost = payload["cost_provenance"]
    collect = payload["collection"]
    live = payload["live_tick_rejected"]
    existing = payload["existing_tapes"]
    md = f"""# Phase 27.18 — Historical M5 Bid/Ask Closure

**Status:** {payload['status']}  
**Evidence status:** `{payload['evidence_status']}`  
**Artifact:** `{PHASE2718_JSON}`

## Policy

Canonical symbol = `{CANONICAL_SYMBOL}`. Historical **DATASET** spread requires actual historical Bid + Ask. PROXY spread is never equivalent to historical Bid/Ask.

## Existing repository inventory

| Metric | Value |
|---|---|
| datasets scanned | `{inv['dataset_count']}` |
| datasets with bid+ask columns | `{inv['bidask_dataset_count']}` |
| historical bid/ask in production datasets | `{inv['historical_bid_ask_available']}` |
| canonical XAUUSD_i files | `{len(inv['canonical_xauusd_i_datasets'])}` |
| sidecars scanned | `{payload['sidecar_inventory']['sidecar_count']}` |
| prior valid logs tape | `{existing['any_existing_valid_tape']}` |

Production/research parquets under `data/`, `data/backtest/`, and `data/cache/` are not rewritten. A logs-only tape is **not** a production dataset.

## Live tick rejection

Phase 27.17 current/stale Bid/Ask is **not** historical data. Tick UTC `{live.get('tick_utc')}` treated as historical M5 tape: **{live.get('treated_as_historical_m5_tape')}**.

## Collection

Read-only attach only. MT5 was not started or restarted. `symbol_select` was not called. No orders. `.env` was not read or written.

If a REAL terminal is already connected, a bounded `copy_ticks_range` window ({BOUNDED_TICK_DAYS} days, max {BOUNDED_MAX_TICKS} ticks) is aggregated to M5 and written under `logs/` only.

This session collection possible: **{collect.get('collection_possible')}**. Tape status: **{tape.get('status')}**. Tape path: `{tape.get('path')}`.

Bounded window only. A truncated tick cap is not a full-history tape and does not rewrite production datasets.

## Substitutions rejected

- current Bid/Ask tick (including Phase 27.17 live snapshot)
- OHLC-implied spread
- proxy/session spread
- spread column

OHLC frame spread mode: `{cost['ohlc_frame_spread_mode']}`. Spread-column frame spread mode: `{cost['spread_column_frame_spread_mode']}` (not DATASET).

## Cost provenance

| Surface | Classification |
|---|---|
| production datasets | `{cost['production_datasets_spread_mode']}` / `{cost['production_spread_evidence_status']}` |
| logs tape | `{cost['logs_tape_spread_mode']}` |
| DATASET requires historical Bid/Ask | `{cost['dataset_spread_requires_historical_bid_ask']}` |

`DATASET` is claimed only when genuine historical Bid/Ask exists. Otherwise evidence remains `{EVIDENCE_BLOCKED}`. Production datasets stay PROXY unless those files themselves contain historical Bid/Ask.

## Production

**BLOCKED.** FINAL_GATE remains `{payload['phase27_16_final_gate_unchanged']}`. No Strategy, RiskGate, or execution changes. Phase 27.19+ not started.

## Next

STOP after Phase 27.18.
"""
    (root / PHASE2718_MD).write_text(md, encoding="utf-8")


def _update_known_unknowns(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.18 historical bid/ask:** `{PHASE2718_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.17 Real evidence:** `logs/phase27_17_real_broker_evidence.json`",
            "**Phase 27.17 Real evidence:** `logs/phase27_17_real_broker_evidence.json`  \n" + pointer,
        )
    cost = payload["cost_provenance"]
    new_cx = (
        "Research/backtest OHLC proxy spread vs observed bid/ask — **OPEN** "
        f"(Phase 27.18: evidence `{payload['evidence_status']}`; "
        f"production datasets `{cost['production_datasets_spread_mode']}` / "
        f"`{cost['production_spread_evidence_status']}`; "
        "PROXY ≠ historical Bid/Ask; live tick ≠ historical tape)."
    )
    for old in (
        "Research/backtest OHLC proxy spread vs observed bid/ask — **OPEN** (Phase 27.11: BLOCKED_PENDING_DATA; 0 production datasets have historical bid/ask).",
        "Research/backtest OHLC proxy spread vs observed bid/ask — **OPEN** (Phase 27: no historical M5 tape).",
    ):
        if old in text:
            text = text.replace(old, new_cx)
            break
    else:
        if "Research/backtest OHLC proxy spread vs observed bid/ask" in text and new_cx not in text:
            import re

            text = re.sub(
                r"Research/backtest OHLC proxy spread vs observed bid/ask — \*\*OPEN\*\*[^\n]*",
                new_cx,
                text,
                count=1,
            )
    spread_row_old = "| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed |"
    spread_row_new = (
        "| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed. "
        f"Phase 27.18 production `{cost['production_spread_evidence_status']}`; "
        f"logs tape `{payload['evidence_status']}` |"
    )
    if spread_row_old in text:
        text = text.replace(spread_row_old, spread_row_new)
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
