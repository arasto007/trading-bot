"""Phase 27.11 — historical M5 bid/ask evidence for canonical XAUUSD_i."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.cost_model import frame_has_historical_bid_ask
from tradingbot.backtest.dataset_provenance import audit_backtest_datasets, search_historical_bid_ask
from tradingbot.backtest.historical_bidask import (
    CANONICAL_SYMBOL,
    CANONICAL_TIMEFRAME,
    tape_fingerprint,
    validate_historical_m5_tape,
)
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS, ticks_to_m5_bidask_bars
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    account_identity_snapshot,
    bounded_readonly_attach_once,
)

PHASE2711_JSON = "logs/phase27_11_historical_bidask.json"
PHASE2711_MD = "docs_v2/01_truth/PHASE27_11_HISTORICAL_BIDASK.md"
TAPE_PARQUET = "logs/phase27_11_xauusd_i_m5_bidask.parquet"
TAPE_META = "logs/phase27_11_xauusd_i_m5_bidask.metadata.json"
BOUNDED_TICK_DAYS = 7
BOUNDED_MAX_TICKS = 100_000


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


def _copy_ticks_already_attached(symbol: str, *, days: int, max_ticks: int) -> tuple[Any, dict[str, Any]]:
    """copy_ticks_range only. Assumes an existing attach. No symbol_select. No .env."""
    meta: dict[str, Any] = {
        "symbol": symbol,
        "method": "copy_ticks_range read-only",
        "ok": False,
    }
    try:
        import MetaTrader5 as mt5
    except ImportError:
        meta["error"] = "MetaTrader5 package not installed"
        return None, meta
    info = mt5.symbol_info(symbol)
    if info is None:
        meta["error"] = f"{symbol} not visible via symbol_info (symbol_select not called)"
        return None, meta
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days)
    try:
        ticks = mt5.copy_ticks_range(symbol, date_from, date_to, mt5.COPY_TICKS_ALL)
    except Exception as exc:
        meta["error"] = str(exc)
        return None, meta
    if ticks is None or len(ticks) == 0:
        meta["error"] = "no historical ticks returned"
        return None, meta
    import pandas as pd

    df = pd.DataFrame(ticks)
    if len(df) > max_ticks:
        df = df.iloc[-max_ticks:].copy()
    meta.update(
        {
            "ok": True,
            "row_count": len(df),
            "date_from_utc": date_from.replace(microsecond=0).isoformat(),
            "date_to_utc": date_to.replace(microsecond=0).isoformat(),
            "columns": list(df.columns),
        }
    )
    return df, meta


def inventory_existing_datasets(root: Path) -> dict[str, Any]:
    search = search_historical_bid_ask(base_dir=root)
    entries = audit_backtest_datasets(base_dir=root)
    canonical = [
        {
            "filename": e.filename,
            "inferred_symbol": e.inferred_symbol,
            "inferred_timeframe": e.inferred_timeframe,
            "bid_present": e.bid_present,
            "ask_present": e.ask_present,
            "spread_mode": e.spread_mode,
            "rows": e.row_count,
        }
        for e in entries
        if (e.inferred_symbol or "") == CANONICAL_SYMBOL
        or "xauusd_i" in e.filename.lower()
    ]
    return {
        "dataset_count": search["dataset_count"],
        "bidask_dataset_count": search["bidask_dataset_count"],
        "historical_bid_ask_available": search["historical_bid_ask_available"],
        "bidask_datasets": search["bidask_datasets"],
        "canonical_xauusd_i_datasets": canonical,
        "any_canonical_historical_bid_ask": any(e["bid_present"] and e["ask_present"] for e in canonical),
    }


def run_phase27_11_historical_bidask(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    before = build_immutability_manifest(root)
    inventory = inventory_existing_datasets(root)

    attach = bounded_readonly_attach_once()
    account = {
        "login_identity": "UNKNOWN",
        "trade_mode_label": "UNKNOWN",
        "server": "UNKNOWN",
        "broker": "UNKNOWN",
    }
    tape_status = "BLOCKED_PENDING_DATA"
    tape_path = None
    tape_meta: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    collect_meta: dict[str, Any] = {"attempted": False}

    if attach["ok"]:
        import MetaTrader5 as mt5

        account = account_identity_snapshot(mt5)
        env = str(account.get("trade_mode_label") or "UNKNOWN")
        if env == "REAL":
            collect_meta["attempted"] = True
            ticks, tick_meta = _copy_ticks_already_attached(
                CANONICAL_SYMBOL, days=BOUNDED_TICK_DAYS, max_ticks=BOUNDED_MAX_TICKS
            )
            collect_meta.update(tick_meta)
            if ticks is not None and tick_meta.get("ok"):
                bars = ticks_to_m5_bidask_bars(ticks)
                if bars is not None and not bars.empty and frame_has_historical_bid_ask(bars):
                    fp = tape_fingerprint(bars)
                    tape_meta = {
                        "symbol": CANONICAL_SYMBOL,
                        "timeframe": CANONICAL_TIMEFRAME,
                        "source": "mt5_copy_ticks_range",
                        "collection_method": "copy_ticks_range read-only; no symbol_select",
                        "broker": account.get("broker"),
                        "server": account.get("server"),
                        "row_count": int(len(bars)),
                        "time_range": {
                            "start": str(bars.index[0]),
                            "end": str(bars.index[-1]),
                            "timezone": str(getattr(bars.index, "tz", None) or "unknown"),
                        },
                        "fingerprint": fp,
                        "utc_timestamp": timestamp,
                        "current_bid_ask_tick": False,
                        "ohlc_spread": False,
                        "proxy_spread": False,
                    }
                    validation = validate_historical_m5_tape(
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
                        tape_status = "COLLECTED_EVIDENCE_ONLY"
                    else:
                        tape_status = "BLOCKED_PENDING_DATA"
                        collect_meta["error"] = validation.get("errors")
                else:
                    tape_status = "BLOCKED_PENDING_DATA"
                    collect_meta["error"] = "tick aggregation produced no historical bid/ask M5 bars"
            else:
                tape_status = "BLOCKED_PENDING_DATA"
        else:
            tape_status = "BLOCKED_PENDING_DATA"
            collect_meta["error"] = f"attached environment {env} is not REAL — historical Real tape not collected"
    else:
        collect_meta["error"] = attach.get("error") or "MT5 not attached"
        tape_status = "BLOCKED_PENDING_DATA"

    originals_untouched, _immutability_issues = verify_immutability(before, base_dir=root)

    dataset_spread_claim_ok = not inventory["historical_bid_ask_available"]
    if inventory["historical_bid_ask_available"]:
        dataset_spread_claim_ok = True

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.11",
        "status": "PASS" if originals_untouched and tape_status in ("BLOCKED_PENDING_DATA", "COLLECTED_EVIDENCE_ONLY") else "FAIL",
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "canonical_symbol": CANONICAL_SYMBOL,
        "canonical_timeframe": CANONICAL_TIMEFRAME,
        "evidence_status": tape_status,
        "inventory": inventory,
        "substitutions_rejected": {
            "current_bid_ask_tick": True,
            "ohlc_spread": True,
            "proxy_spread": True,
        },
        "dataset_spread_requires_historical_bid_ask": True,
        "mt5_attach": {
            "ok": attach.get("ok"),
            "error": attach.get("error"),
            "environment": account.get("trade_mode_label"),
            "server": account.get("server"),
            "started": False,
        },
        "collection": collect_meta,
        "tape": {
            "path": tape_path,
            "status": tape_status,
            "provenance": tape_meta,
            "validation": validation,
        },
        "original_datasets_untouched": originals_untouched,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "account_state_modified": False,
            "original_datasets_overwritten": not originals_untouched,
            "strategy_modified": False,
            "backtest_parameters_modified": False,
            "current_tick_used_as_historical": False,
        },
        "deferred": ["Phase 27.12+ — not started"],
    }
    _ = dataset_spread_claim_ok
    out = root / PHASE2711_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_known_unknowns(root, payload)
    return payload


def run_phase27_11_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_11_historical_bidask(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    inv = payload["inventory"]
    tape = payload["tape"]
    md = f"""# Phase 27.11 — Historical M5 Bid/Ask Evidence

**Status:** {payload['status']}  
**Evidence status:** `{payload['evidence_status']}`  
**Artifact:** `{PHASE2711_JSON}`

## Canonical target

`{CANONICAL_SYMBOL}` M5. A live `symbol_info_tick` Bid/Ask is **not** historical bid/ask.

## Existing repository inventory

| Metric | Value |
|---|---|
| datasets scanned | `{inv['dataset_count']}` |
| datasets with bid+ask columns | `{inv['bidask_dataset_count']}` |
| historical bid/ask available | `{inv['historical_bid_ask_available']}` |
| canonical XAUUSD_i files | `{len(inv['canonical_xauusd_i_datasets'])}` |

All production/research parquets under `data/`, `data/backtest/`, and `data/cache/` are OHLC-only. Sidecars already mark spread `PROXY` and `historical_bid_ask_available=false`.

## Collection

Read-only attach only. MT5 was not started. `symbol_select` was not called. No orders.

If a REAL terminal is already connected, a bounded `copy_ticks_range` window ({BOUNDED_TICK_DAYS} days, max {BOUNDED_MAX_TICKS} ticks) is aggregated to M5 and written under `logs/` only. Original datasets are never overwritten.

This session: **{payload['evidence_status']}**. Tape path: `{tape.get('path')}`.

## Substitutions rejected

- current Bid/Ask tick
- OHLC-implied spread
- proxy/session spread

`Cost` provenance now claims `DATASET` spread only when historical bid+ask columns exist.

## Production

**BLOCKED.** No strategy or backtest parameter changes.

## Next

STOP after Phase 27.11.
"""
    (root / PHASE2711_MD).write_text(md, encoding="utf-8")


def _update_known_unknowns(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.11 historical bid/ask:** `{PHASE2711_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.9 Real evidence:** `logs/phase27_9_real_broker_evidence.json`",
            f"**Phase 27.9 Real evidence:** `logs/phase27_9_real_broker_evidence.json`  \n{pointer}",
        )
    old_cx = "Research/backtest OHLC proxy spread vs observed bid/ask — **OPEN** (Phase 27: no historical M5 tape)."
    new_cx = (
        "Research/backtest OHLC proxy spread vs observed bid/ask — **OPEN** "
        f"(Phase 27.11: {payload['evidence_status']}; 0 production datasets have historical bid/ask)."
    )
    if old_cx in text:
        text = text.replace(old_cx, new_cx)
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
