"""Phase 37 — longest defensible XAUUSD_i historical tape (attach-only).

RESEARCH / DATA ACQUISITION ONLY. Does not start MT5, start the bot, send
orders, read .env, silently map XAUUSD, overwrite the Phase 28/30 snapshot,
optimize, or evaluate the strategy.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.backtest.dataset_contract import classify_dataset_binding
from tradingbot.backtest.dataset_provenance import (
    DatasetMetadata,
    EconomicsProvenance,
    MappingStatus,
    save_dataset_metadata,
)
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    UNKNOWN,
    account_identity_snapshot,
    bounded_readonly_attach_once,
    catalog_existence_check,
    inspect_symbol_readonly,
    terminal64_running,
    terminal_build_snapshot,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_23_bidask_expansion import _copy_ticks_chunk
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    load_parquet_utc,
)
from tradingbot.backtest.phase29_research_tape import (
    audit_dataset,
    content_fingerprint,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.domain.position_logic import pip_size

PHASE = "37"
PHASE37_JSON = "logs/phase37_long_horizon_tape.json"
PHASE37_MD = "docs_v2/02_research/PHASE37_LONG_HORIZON_TAPE.md"
PHASE37_M5 = "data/XAUUSD_i_5m_phase37.parquet"
PHASE37_M15 = "data/XAUUSD_i_15m_phase37.parquet"
PHASE37_M1 = "data/XAUUSD_i_m1_phase37.parquet"
PHASE37_TICKS = "data/XAUUSD_i_ticks_phase37.parquet"
PHASE37_BIDASK = "logs/phase37_xauusd_i_bidask.parquet"
CANONICAL_SYMBOL = "XAUUSD_i"
LOGICAL_SYMBOL = "XAUUSD"
TARGET_DAYS = 180
MIN_DAYS = 60
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15}
RATES_CHUNK = 20_000
MAX_BARS = {"M5": 250_000, "M15": 50_000, "M1": 30_000}
TICK_LOOKBACK_DAYS = 7
TICK_CHUNK_HOURS = 6
MAX_TICKS = 300_000
MAX_TICK_CHUNKS = 40
NY_START_HOUR = 15
NY_END_HOUR = 16
ASIAN_START_HOUR = 0
ASIAN_END_HOUR = 8
FROZEN_WRITE_PATHS = {CANONICAL_PARQUET, "data/XAUUSD_i_4h.parquet"}
SYMBOL_TRADE_MODE = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY", 3: "CLOSEONLY", 4: "FULL"}

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "production_changes",
    "terminal",
    "symbols",
    "m5",
    "coverage",
    "gaps",
    "bid_ask",
    "m15",
    "m1",
    "ticks",
    "fingerprints",
    "dataset_binding",
    "provenance",
    "limitations",
    "FINAL_GATE",
    "phase_38_started",
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
    return UNKNOWN


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def terminal64_inventory() -> dict[str, Any]:
    """Count running terminal64.exe processes. Does not start or attach."""
    inventory = {
        "image": "terminal64.exe",
        "running": False,
        "count": 0,
        "pids": [],
        "multiple": False,
        "error": None,
    }
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        text = out.stdout or ""
        pids: list[str] = []
        for line in text.splitlines():
            if "terminal64.exe" not in line.lower():
                continue
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.append(parts[1])
        inventory["count"] = len(pids)
        inventory["pids"] = pids
        inventory["running"] = len(pids) > 0
        inventory["multiple"] = len(pids) > 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        inventory["error"] = str(exc)
        inventory["running"] = terminal64_running()
        inventory["count"] = 1 if inventory["running"] else 0
    return inventory


def strategy_window_coverage(df: pd.DataFrame, *, step_minutes: int = 5) -> dict[str, Any]:
    """NY 15–16 and Asian 00–08 UTC coverage. Missing windows are not fabricated."""
    empty = {
        "ny_15_16_utc": {"expected_bars": 0, "observed_bars": 0, "missing_bars": 0, "coverage_pct": 0.0},
        "asian_00_08_utc": {"expected_bars": 0, "observed_bars": 0, "missing_bars": 0, "coverage_pct": 0.0},
        "strategy_validation_coverage_claimed": False,
        "reason": "empty tape",
    }
    if df is None or df.empty:
        return empty
    idx = pd.to_datetime(df.index, utc=True)
    start, end = idx[0], idx[-1]
    observed = pd.DatetimeIndex(idx.floor(f"{step_minutes}min")).unique()

    def _expected(start_hour: int, end_hour: int) -> pd.DatetimeIndex:
        times: list[pd.Timestamp] = []
        cursor = start.tz_convert("UTC").normalize()
        last = end.tz_convert("UTC").normalize()
        delta = pd.Timedelta(minutes=step_minutes)
        while cursor <= last:
            if int(cursor.weekday()) < 5:
                slot = cursor + pd.Timedelta(hours=start_hour)
                window_end = cursor + pd.Timedelta(hours=end_hour)
                while slot < window_end:
                    if start <= slot <= end:
                        times.append(slot)
                    slot += delta
            cursor += pd.Timedelta(days=1)
            if len(times) > 2_000_000:
                break
        return pd.DatetimeIndex(times, tz="UTC")

    def _pack(expected: pd.DatetimeIndex) -> dict[str, Any]:
        if len(expected) == 0:
            return {"expected_bars": 0, "observed_bars": 0, "missing_bars": 0, "coverage_pct": 0.0}
        have = int(expected.isin(observed).sum())
        missing = int(len(expected) - have)
        return {
            "expected_bars": int(len(expected)),
            "observed_bars": have,
            "missing_bars": missing,
            "coverage_pct": round(100.0 * have / max(len(expected), 1), 4),
        }

    ny = _pack(_expected(NY_START_HOUR, NY_END_HOUR))
    asian = _pack(_expected(ASIAN_START_HOUR, ASIAN_END_HOUR))
    days = float((end - start).total_seconds() / 86400.0)
    claimed = days >= MIN_DAYS and ny["missing_bars"] == 0 and asian["missing_bars"] == 0
    return {
        "ny_15_16_utc": ny,
        "asian_00_08_utc": asian,
        "strategy_validation_coverage_claimed": claimed,
        "reason": (
            "required strategy windows fully present and duration meets 60-day floor"
            if claimed
            else "do not claim strategy validation coverage: missing session bars and/or duration < 60d"
        ),
    }


def _enrich_symbol(mt5: Any, symbol: str, catalog: dict[str, Any]) -> dict[str, Any]:
    row = inspect_symbol_readonly(mt5, symbol)
    exact = ((catalog.get("exact_matches") or {}).get(symbol) or UNKNOWN)
    if row.get("existence") != "YES" and exact == "NO":
        row["existence"] = "ABSENT_ON_OBSERVED_TERMINAL"
        row["broker_wide_absence_concluded"] = False
    else:
        row["broker_wide_absence_concluded"] = False
    info = mt5.symbol_info(symbol) if row.get("existence") in {"YES"} else None
    if info is not None:
        selected = getattr(info, "select", None)
        row["selectable"] = "YES" if selected else "NO" if selected is not None else UNKNOWN
        mode = getattr(info, "trade_mode", None)
        row["trade_mode"] = mode if mode is not None else UNKNOWN
        try:
            row["trade_mode_label"] = SYMBOL_TRADE_MODE.get(int(mode), UNKNOWN) if mode is not None else UNKNOWN
        except (TypeError, ValueError):
            row["trade_mode_label"] = UNKNOWN
    else:
        row["selectable"] = UNKNOWN
        row["trade_mode"] = UNKNOWN
        row["trade_mode_label"] = UNKNOWN
    row["symbol_select_called"] = False
    return row


def _rates_to_frame(rates: Any) -> pd.DataFrame:
    frame = pd.DataFrame(rates)
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
    frame = frame.set_index("time").sort_index()
    if "tick_volume" in frame.columns and "volume" not in frame.columns:
        frame["volume"] = frame["tick_volume"]
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in frame.columns]
    return frame[keep].copy()


def collect_ohlc_chunked(*, timeframe: str, attached: bool) -> dict[str, Any]:
    """Bounded copy_rates_from_pos. No symbol_select, no orders, no terminal start."""
    meta: dict[str, Any] = {
        "symbol": CANONICAL_SYMBOL,
        "timeframe": timeframe,
        "method": "copy_rates_from_pos chunked; attach-only; no symbol_select",
        "ok": False,
        "partial": False,
        "rows": 0,
        "chunks": 0,
        "status": "NOT_OBSERVED",
        "error": None,
        "retrieval_timestamp_utc": _utc_now(),
    }
    if not attached:
        meta["error"] = "attach not available — collection skipped (MT5 was not started)"
        meta["status"] = "BLOCKED"
        return meta
    try:
        import MetaTrader5 as mt5
    except ImportError:
        meta["error"] = "MetaTrader5 package not installed"
        meta["status"] = "BLOCKED"
        return meta
    tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M1": mt5.TIMEFRAME_M1}
    tf_const = tf_map[timeframe]
    info = mt5.symbol_info(CANONICAL_SYMBOL)
    if info is None:
        meta["error"] = "XAUUSD_i not present in attached catalog (symbol_info None). symbol_select was not called."
        meta["status"] = "NOT_OBSERVED"
        return meta
    frames: list[pd.DataFrame] = []
    pos = 0
    cap = MAX_BARS[timeframe]
    try:
        while pos < cap:
            want = min(RATES_CHUNK, cap - pos)
            rates = mt5.copy_rates_from_pos(CANONICAL_SYMBOL, tf_const, pos, want)
            meta["chunks"] += 1
            if rates is None or len(rates) == 0:
                break
            frames.append(_rates_to_frame(rates))
            got = int(len(rates))
            pos += got
            if got < want:
                break
    except Exception as exc:
        meta["partial"] = True
        meta["error"] = str(exc)
    if not frames:
        meta["error"] = meta.get("error") or "copy_rates_from_pos returned no rows"
        meta["status"] = "NOT_OBSERVED"
        return meta
    frame = pd.concat(frames).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    meta["ok"] = True
    meta["status"] = "PARTIAL" if meta["partial"] else "OBSERVED"
    meta["rows"] = int(len(frame))
    meta["start"] = str(frame.index[0])
    meta["end"] = str(frame.index[-1])
    meta["duration_days"] = float((frame.index[-1] - frame.index[0]).total_seconds() / 86400.0)
    meta["target_days"] = TARGET_DAYS
    meta["minimum_days"] = MIN_DAYS
    meta["below_minimum_60d"] = bool(meta["duration_days"] < MIN_DAYS)
    meta["below_preferred_180d"] = bool(meta["duration_days"] < TARGET_DAYS)
    meta["frame"] = frame
    return meta


def collect_ticks_bounded(*, attached: bool, end: datetime | None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "ok": False,
        "status": "NOT_OBSERVED",
        "rows": 0,
        "chunks": 0,
        "partial": False,
        "resource_bound": False,
        "lookback_days": TICK_LOOKBACK_DAYS,
        "error": None,
        "retrieval_timestamp_utc": _utc_now(),
        "method": "copy_ticks_range bounded 6-hour chunks; attach-only; no symbol_select",
    }
    if not attached:
        meta["error"] = "attach not available — ticks skipped"
        meta["status"] = "BLOCKED"
        return meta
    finish = end or datetime.now(timezone.utc)
    if finish.tzinfo is None:
        finish = finish.replace(tzinfo=timezone.utc)
    start = finish - timedelta(days=TICK_LOOKBACK_DAYS)
    frames: list[pd.DataFrame] = []
    cursor = start
    total = 0
    try:
        while cursor < finish and meta["chunks"] < MAX_TICK_CHUNKS and total < MAX_TICKS:
            nxt = min(cursor + timedelta(hours=TICK_CHUNK_HOURS), finish)
            df, chunk_meta = _copy_ticks_chunk(CANONICAL_SYMBOL, cursor, nxt)
            meta["chunks"] += 1
            if df is not None and not df.empty:
                remain = MAX_TICKS - total
                if len(df) > remain:
                    df = df.iloc[:remain].copy()
                    meta["partial"] = True
                    meta["resource_bound"] = True
                frames.append(df)
                total += int(len(df))
            if chunk_meta.get("error"):
                meta["partial"] = True
                meta["error"] = chunk_meta.get("error")
                break
            cursor = nxt
            if meta["resource_bound"]:
                break
    except Exception as exc:
        meta["partial"] = True
        meta["error"] = str(exc)
    if not frames:
        meta["status"] = "NOT_OBSERVED"
        return meta
    frame = pd.concat(frames, ignore_index=True)
    meta["ok"] = True
    meta["status"] = "PARTIAL" if meta["partial"] or meta["resource_bound"] else "OBSERVED"
    meta["rows"] = int(len(frame))
    meta["columns"] = [str(c) for c in frame.columns]
    meta["frame"] = frame
    return meta


def _ticks_to_bidask(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    frame = df.copy()
    if "time" in frame.columns:
        ts = pd.to_datetime(frame["time"], unit="s", utc=True, errors="coerce")
        if ts.isna().all():
            ts = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        frame = frame.set_index(ts)
    if "bid" not in frame.columns or "ask" not in frame.columns:
        return pd.DataFrame()
    out = frame[["bid", "ask"]].copy()
    out = out[out.index.notna()].sort_index()
    return out[~out.index.duplicated(keep="last")]


def spread_stats(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty or "bid" not in df.columns or "ask" not in df.columns:
        return {"available": False, "status": "NOT_OBSERVED", "grade": None, "not_proxy": True, "not_modeled": True}
    bid = pd.to_numeric(df["bid"], errors="coerce")
    ask = pd.to_numeric(df["ask"], errors="coerce")
    valid = bid.notna() & ask.notna() & (bid > 0) & (ask > 0) & (ask >= bid)
    spread = (ask - bid).loc[valid]
    if spread.empty:
        return {"available": False, "status": "NOT_OBSERVED", "grade": None, "not_proxy": True, "not_modeled": True}
    pip = pip_size(CANONICAL_SYMBOL)
    pips = spread / pip
    idx = pd.to_datetime(spread.index, utc=True)

    def _pct(series: pd.Series, q: float) -> float:
        return float(np.percentile(series, q))

    def _window(hours: tuple[int, ...], weekdays_only: bool | None = None) -> dict[str, Any]:
        mask = idx.hour.isin(hours)
        if weekdays_only is True:
            mask = mask & (idx.weekday < 5)
        elif weekdays_only is False:
            mask = mask & (idx.weekday >= 5)
        series = pips[mask]
        if series.empty:
            return {"n": 0, "status": "NOT_OBSERVED"}
        return {
            "n": int(len(series)),
            "median": float(series.median()),
            "p75": _pct(series, 75),
            "p90": _pct(series, 90),
            "p95": _pct(series, 95),
            "p99": _pct(series, 99),
            "max": float(series.max()),
            "status": "OBSERVED",
        }

    by_hour = {
        str(h): float(pips[idx.hour == h].median())
        for h in range(24)
        if (idx.hour == h).any()
    }
    return {
        "available": True,
        "status": "OBSERVED",
        "grade": "OBSERVED",
        "not_proxy": True,
        "not_modeled": True,
        "n": int(len(spread)),
        "median": float(spread.median()),
        "p75": _pct(spread, 75),
        "p90": _pct(spread, 90),
        "p95": _pct(spread, 95),
        "p99": _pct(spread, 99),
        "max": float(spread.max()),
        "median_pips": float(pips.median()),
        "p75_pips": _pct(pips, 75),
        "p90_pips": _pct(pips, 90),
        "p95_pips": _pct(pips, 95),
        "p99_pips": _pct(pips, 99),
        "max_pips": float(pips.max()),
        "by_hour_utc_median_pips": by_hour,
        "ny_15_16_utc": _window((15,), weekdays_only=True),
        "rollover_21_00_utc": _window((21, 22, 23, 0)),
        "weekend": _window(tuple(range(24)), weekdays_only=False),
        "pip_size_heuristic": pip,
        "first_timestamp": str(idx[0]),
        "last_timestamp": str(idx[-1]),
    }


def _refuse_frozen(dest: str) -> None:
    if dest.replace("\\", "/") in FROZEN_WRITE_PATHS:
        raise RuntimeError(f"refusing to overwrite frozen snapshot {dest}")


def write_research_parquet(root: Path, frame: pd.DataFrame, dest: str) -> dict[str, Any]:
    _refuse_frozen(dest)
    path = root / dest
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    ohlc = all(col in frame.columns for col in ("open", "high", "low", "close"))
    content_fp = (
        content_fingerprint(frame)
        if isinstance(frame.index, pd.DatetimeIndex) and ohlc
        else None
    )
    return {
        "path": dest,
        "written": True,
        "rows": int(len(frame)),
        "file_fingerprint": file_fingerprint(path),
        "content_fingerprint": content_fp,
    }


def _write_m5_sidecar(root: Path, dest: str, *, account: dict[str, Any], audit: dict[str, Any], fp: str) -> None:
    path = root / dest
    save_dataset_metadata(
        path,
        DatasetMetadata(
            dataset_symbol=CANONICAL_SYMBOL,
            configured_instrument_symbol=PRIMARY_SYMBOL,
            dataset_symbol_map={},
            mapping_status=MappingStatus.MATCH.value,
            economics_source=EconomicsProvenance.UNKNOWN.value,
            timeframe="M5",
            datetime_range={
                "start": audit.get("first_timestamp"),
                "end": audit.get("last_timestamp"),
                "timezone": "UTC",
                "row_count": audit.get("row_count"),
            },
            spread_mode="PROXY",
            spread_source="ohlc_only",
            spread_status="UNKNOWN",
            historical_bid_ask_available=False,
            broker=str(account.get("broker") or UNKNOWN),
            server=str(account.get("server") or UNKNOWN),
            account_environment=str(account.get("trade_mode_label") or UNKNOWN),
            evidence_timestamp=_utc_now(),
            source_artifact=dest,
            symbol_equivalence="NOT_PROVEN",
            provenance_summary=(
                f"Phase 37 attach-only XAUUSD_i M5 copy. dataset_symbol_map empty. "
                f"file_fingerprint={fp}. Frozen {CANONICAL_PARQUET} was not overwritten."
            ),
        ),
    )


def attach_session() -> dict[str, Any]:
    inventory = terminal64_inventory()
    session: dict[str, Any] = {
        "attach_only": True,
        "mt5_started_by_script": False,
        "mt5_restarted_by_script": False,
        "symbol_select_called": False,
        "orders_sent": False,
        "env_accessed": False,
        "inventory": inventory,
        "status": "BLOCKED",
        "ok": False,
        "error": None,
        "broker": UNKNOWN,
        "server": UNKNOWN,
        "environment": UNKNOWN,
        "path": UNKNOWN,
        "build": UNKNOWN,
        "connected": False,
        "retrieval_timestamp_utc": _utc_now(),
        "multiple_terminals": bool(inventory.get("multiple")),
        "note": None,
    }
    if not inventory.get("running"):
        session["error"] = "terminal64.exe not running — attach skipped (MT5 was not started)"
        session["status"] = "BLOCKED"
        return session
    if inventory.get("multiple"):
        session["note"] = (
            "Multiple terminal64.exe processes observed. This phase did not guess. "
            "MetaTrader5 IPC attach was used; identity below is whatever terminal_info returned."
        )
    attach = bounded_readonly_attach_once()
    session["attach_attempt"] = {
        k: attach.get(k)
        for k in (
            "ok",
            "method",
            "error",
            "attach_only",
            "mt5_started_by_script",
            "symbol_select_called",
            "orders_sent",
            "env_file_read",
        )
    }
    if not attach.get("ok"):
        session["error"] = attach.get("error") or "MT5 attach-only failed"
        session["status"] = "NOT_ATTACHED"
        return session
    try:
        import MetaTrader5 as mt5
    except ImportError:
        session["error"] = "MetaTrader5 package not installed"
        session["status"] = "NOT_ATTACHED"
        return session
    account = account_identity_snapshot(mt5)
    term = terminal_build_snapshot(mt5)
    info = mt5.terminal_info()
    session["ok"] = True
    session["status"] = "ATTACHED"
    session["broker"] = account.get("broker") or UNKNOWN
    session["server"] = account.get("server") or UNKNOWN
    session["environment"] = account.get("trade_mode_label") or UNKNOWN
    session["login_identity"] = account.get("login_identity") or UNKNOWN
    session["build"] = term.get("build") or UNKNOWN
    session["connected"] = bool(term.get("connected"))
    session["terminal_name"] = term.get("name") or UNKNOWN
    session["path"] = str(getattr(info, "path", None) or UNKNOWN) if info is not None else UNKNOWN
    session["account"] = account
    session["catalog"] = catalog_existence_check(mt5)
    session["symbols"] = {
        CANONICAL_SYMBOL: _enrich_symbol(mt5, CANONICAL_SYMBOL, session["catalog"]),
        LOGICAL_SYMBOL: _enrich_symbol(mt5, LOGICAL_SYMBOL, session["catalog"]),
    }
    return session


def _dataset_summary(block: dict[str, Any], path: str | None) -> dict[str, Any]:
    return {
        "path": path,
        "status": block.get("status"),
        "ok": bool(block.get("ok")),
        "start": block.get("start"),
        "end": block.get("end"),
        "days": block.get("duration_days"),
        "rows": block.get("rows") or 0,
        "partial": bool(block.get("partial")),
        "error": block.get("error"),
        "below_minimum_60d": block.get("below_minimum_60d"),
        "below_preferred_180d": block.get("below_preferred_180d"),
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    term = payload["terminal"]
    m5 = payload["m5"]
    ba = payload["bid_ask"]
    (root / PHASE37_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE37_MD).write_text(
        f"""# Phase 37 — Long-Horizon XAUUSD_i Historical Tape Acquisition

**STATUS:** `{payload.get("status")}`
**Class:** RESEARCH / DATA ACQUISITION ONLY
**Live trading authorized:** NO
**Production changes:** `{payload.get("production_changes")}`
**Parameters optimized:** NO
**Strategy evaluated:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`

STOP AFTER PHASE 37. DO NOT START PHASE 38.
DO NOT OPTIMIZE. DO NOT ALTER PRODUCTION.

This phase exists to resolve the Phase 36 evidence bottleneck (tape ~14.88 days / 6 events).
The frozen Phase 28/30 snapshot `{CANONICAL_PARQUET}` was **not** overwritten.

---

## TERMINAL

**{term.get("status")}**

- Broker/server: `{term.get("broker")}` / `{term.get("server")}`
- Environment: `{term.get("environment")}`
- Path: `{term.get("path")}`
- Build: `{term.get("build")}`
- Connected: `{term.get("connected")}`
- Multiple terminals: `{term.get("multiple_terminals")}`
- Attach-only: `{term.get("attach_only")}`
- MT5 started by this phase: `{term.get("mt5_started_by_script")}`
- Retrieval: `{term.get("retrieval_timestamp_utc")}`
- Error: `{term.get("error")}`
- Note: {term.get("note") or "none"}

## SYMBOL

- `XAUUSD_i` = `{payload["symbols"]["XAUUSD_i"]["existence"]}`
- `XAUUSD` = `{payload["symbols"]["XAUUSD"]["existence"]}`

`XAUUSD` absence is **ABSENT_ON_OBSERVED_TERMINAL** at most. Broker-wide absence was not concluded.
`dataset_symbol_map` is empty. Silent mapping did not occur. `symbol_select` was not called.

Symbol evidence (XAUUSD_i): `{payload["symbols"]["XAUUSD_i"]}`

## M5

| Field | Value |
|---|---|
| Path | `{m5.get("path")}` |
| Start | {m5.get("start")} |
| End | {m5.get("end")} |
| Days | {m5.get("days")} |
| Rows | {m5.get("rows")} |
| Coverage 24x7 % | {payload["coverage"]["m5"].get("coverage_pct_24x7") if payload["coverage"]["m5"] else None} |
| Coverage weekday 24h % | {payload["coverage"]["m5"].get("coverage_pct_weekday_24h") if payload["coverage"]["m5"] else None} |
| Status | {m5.get("status")} |
| Partial | {m5.get("partial")} |

## TARGET

- 60-day minimum: `{payload["targets"]["minimum_60d_met"]}`
- 180-day preferred: `{payload["targets"]["preferred_180d_met"]}`

Completeness was not fabricated.

## GAPS

`{payload.get("gaps")}`

UNKNOWN_GAP is **not** automatically acceptable.

## BID/ASK

Status: `{ba.get("status")}`  
Grade: `{ba.get("grade")}` (OBSERVED remains separate from PROXY and MODELED)  
Coverage: `{ba.get("coverage_note")}`  
Stats: `{ba.get("stats")}`

Missing Bid/Ask was **not** replaced with proxy values.

## M15

`{payload["m15"]}`

## M1

`{payload["m1"]}`

## TICKS

`{payload["ticks"]}`

## FINGERPRINT

- Frozen Phase 28/30 file: `{payload["fingerprints"]["phase28_m5_file"]}`
- Frozen unchanged: `{payload["fingerprints"]["phase28_m5_unchanged"]}`
- Phase 37 M5 file: `{payload["fingerprints"].get("phase37_m5_file")}`
- Phase 37 M5 content: `{payload["fingerprints"].get("phase37_m5_content")}`

Phase 28 fingerprint is reused only if content is identical.

## CONTENT HASH

`{payload["fingerprints"].get("phase37_m5_content")}`

## DATASET_BINDING

Empty map. Canonical symbol `XAUUSD_i` only. Logical `XAUUSD` was not merged, renamed, or silently bound.

`{payload["dataset_binding"]}`

## PROVENANCE

`{payload["provenance"]}`

## LIMITATIONS

{payload.get("limitations")}

## PRODUCTION_CHANGES

MUST BE NONE — recorded `{payload.get("production_changes")}`.

## NEXT STEP

Do not start Phase 38 from this file. Do not run strategy evaluation. Do not optimize.

## Safety

No live orders, no `.env`, no frozen parquet rewrite, no strategy/RiskGate/ML change.
Phase 38 was **not** started.
""",
        encoding="utf-8",
    )


def _patch_truth_docs(root: Path, *, status: str, terminal_status: str) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Long-horizon tape (Phase 37)"
        block = (
            "\n\n## Long-horizon tape (Phase 37)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            f"| Phase 37 status | **{status}** |\n"
            f"| Terminal | **{terminal_status}** |\n"
            "| Frozen Phase 28/30 M5 overwritten | **NO** |\n"
            "| Silent XAUUSD→XAUUSD_i map | **NO** |\n"
            "| MT5 started by this phase | **NO** |\n"
            "| Production changed / optimized / strategy evaluated | **NO** |\n"
            "| Phase 38 started | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")
        else:
            start = text.find(marker)
            rest = text.find("\n## ", start + 5)
            text = text[:start].rstrip() + block + (text[rest:] if rest >= 0 else "")
            known.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        text = text.replace(
            "| Phase 36 strategy verdict | `run_phase36_collection()` | n/a | RESEARCH ONLY; synthesize 28.0–35; no optimization; no production change | **PASS** — INSUFFICIENT_EVIDENCE; FINAL_GATE BLOCKED; Phase 37 not started |",
            "| Phase 36 strategy verdict | `run_phase36_collection()` | n/a | RESEARCH ONLY; synthesize 28.0–35; no optimization; no production change | **PASS** — INSUFFICIENT_EVIDENCE; FINAL_GATE BLOCKED |",
        )
        row = (
            f"| Phase 37 long-horizon tape | `run_phase37_collection()` | n/a | RESEARCH/data-acquisition; attach-only XAUUSD_i M5; never overwrite frozen Phase 28 snapshot | **{status}** — terminal {terminal_status}; Phase 38 not started |"
        )
        text = re.sub(
            r"\| Phase 37 long-horizon tape \|.*\n",
            row + "\n",
            text,
        )
        if "Phase 37 long-horizon tape" not in text:
            needle = "| Phase 36 strategy verdict |"
            idx = text.find(needle)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + row + "\n" + text[end + 1 :]
        cfg.write_text(text, encoding="utf-8")
    sot = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    if sot.is_file():
        text = sot.read_text(encoding="utf-8")
        para = (
            "Phase 37 (`docs_v2/02_research/PHASE37_LONG_HORIZON_TAPE.md`) is attach-only "
            "long-horizon `XAUUSD_i` tape acquisition. It does not overwrite the Phase 28/30 "
            "canonical M5 snapshot, does not merge logical `XAUUSD`, and does not authorize live trading.\n"
        )
        if "PHASE37_LONG_HORIZON_TAPE.md" not in text:
            marker = "Phase 36 (`docs_v2/02_research/PHASE36_STRATEGY_VERDICT.md`)"
            idx = text.find(marker)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + "\n" + para + text[end + 1 :]
                sot.write_text(text, encoding="utf-8")
    boundary = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    if boundary.is_file():
        text = boundary.read_text(encoding="utf-8")
        line = (
            "`tradingbot/backtest/phase37_long_horizon_tape.py` — **RESEARCH_ONLY** attach-only "
            "XAUUSD_i long-horizon tape; does not overwrite Phase 28 canonical M5; does not authorize live trading.  \n"
        )
        if "phase37_long_horizon_tape.py" not in text:
            needle = "`tradingbot/backtest/phase36_strategy_verdict.py`"
            idx = text.find(needle)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + line + text[end + 1 :]
                boundary.write_text(text, encoding="utf-8")


def run_phase37_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    frozen_fp = file_fingerprint(root / CANONICAL_PARQUET)
    if frozen_fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Frozen Phase 28/30 M5 fingerprint changed — Phase 37 refuses to proceed")
    frozen_df = load_parquet_utc(root / CANONICAL_PARQUET)
    frozen_content = content_fingerprint(frozen_df)

    session = attach_session()
    attached = bool(session.get("ok"))
    symbols = session.get("symbols") or {
        CANONICAL_SYMBOL: {"existence": UNKNOWN, "broker_wide_absence_concluded": False},
        LOGICAL_SYMBOL: {"existence": UNKNOWN, "broker_wide_absence_concluded": False},
    }
    account = session.get("account") or {}

    collect_m5 = collect_ohlc_chunked(timeframe="M5", attached=attached)
    m5_frame = collect_m5.pop("frame", None)
    wrote: dict[str, Any] = {}
    m5_audit = None
    windows = strategy_window_coverage(pd.DataFrame())
    if collect_m5.get("ok") and m5_frame is not None and len(m5_frame) > 0:
        wrote["m5"] = write_research_parquet(root, m5_frame, PHASE37_M5)
        m5_audit = audit_dataset(m5_frame, timeframe="M5", path=PHASE37_M5)
        windows = strategy_window_coverage(m5_frame, step_minutes=5)
        _write_m5_sidecar(
            root,
            PHASE37_M5,
            account=account,
            audit=m5_audit,
            fp=wrote["m5"]["file_fingerprint"],
        )

    collect_m15 = {"status": "NOT_ATTEMPTED", "rows": 0, "ok": False}
    collect_m1 = {"status": "NOT_ATTEMPTED", "rows": 0, "ok": False}
    collect_ticks = {"status": "NOT_ATTEMPTED", "rows": 0, "ok": False}
    bidask_stats: dict[str, Any] = {
        "available": False,
        "status": "NOT_OBSERVED",
        "grade": None,
        "not_proxy": True,
        "not_modeled": True,
    }
    if attached and collect_m5.get("ok"):
        collect_m15 = collect_ohlc_chunked(timeframe="M15", attached=True)
        m15_frame = collect_m15.pop("frame", None)
        if collect_m15.get("ok") and m15_frame is not None and len(m15_frame) > 0:
            wrote["m15"] = write_research_parquet(root, m15_frame, PHASE37_M15)
        collect_m1 = collect_ohlc_chunked(timeframe="M1", attached=True)
        m1_frame = collect_m1.pop("frame", None)
        if collect_m1.get("ok") and m1_frame is not None and len(m1_frame) > 0:
            wrote["m1"] = write_research_parquet(root, m1_frame, PHASE37_M1)
        tick_end = None
        if m5_frame is not None and len(m5_frame) > 0:
            tick_end = pd.Timestamp(m5_frame.index[-1]).to_pydatetime()
        collect_ticks = collect_ticks_bounded(attached=True, end=tick_end)
        tick_frame = collect_ticks.pop("frame", None)
        if collect_ticks.get("ok") and tick_frame is not None and len(tick_frame) > 0:
            wrote["ticks"] = write_research_parquet(root, tick_frame, PHASE37_TICKS)
            bidask = _ticks_to_bidask(tick_frame)
            if not bidask.empty:
                wrote["bidask"] = write_research_parquet(root, bidask, PHASE37_BIDASK)
                bidask_stats = spread_stats(bidask)

    days = float(collect_m5.get("duration_days") or 0)
    if not attached:
        status = "BLOCKED"
    elif days >= TARGET_DAYS:
        status = "PASS"
    else:
        status = "PASS_WITH_DEFERRAL"

    xau = symbols.get(LOGICAL_SYMBOL) or {}
    xau_i = symbols.get(CANONICAL_SYMBOL) or {}
    binding = classify_dataset_binding(
        CANONICAL_SYMBOL,
        configured_symbol=PRIMARY_SYMBOL,
        dataset_symbol_map={},
    )
    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    ok_immut, issues = verify_immutability(before, base_dir=root)
    phase37_file_fp = (wrote.get("m5") or {}).get("file_fingerprint")
    phase37_content_fp = (wrote.get("m5") or {}).get("content_fingerprint")
    reused_phase28 = bool(
        phase37_content_fp and phase37_content_fp == frozen_content
    )
    m5_path = PHASE37_M5 if (root / PHASE37_M5).is_file() else None
    limitations = (
        f"Terminal status {session.get('status')}. "
        f"M5 collected days={days:.4f} (minimum {MIN_DAYS}, preferred {TARGET_DAYS}). "
        "Completeness was not fabricated. Logical XAUUSD was not merged. "
        f"Frozen {CANONICAL_PARQUET} fingerprint {frozen_fp} unchanged. "
        "OHLC Phase 37 tape has no Bid/Ask columns (PROXY/ohlc_only). "
        "Tick Bid/Ask, if present, is OBSERVED only for the bounded tick window. "
        "This phase does not evaluate gold_ny_sweep and does not authorize live trading."
    )
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": status,
        "research_only": True,
        "live_trading_authorized": False,
        "production_changes": "NONE",
        "parameters_optimized": False,
        "parameters_searched": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "ml_changed": False,
        "strategy_evaluated": False,
        "silent_xauusd_mapping": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "terminal": session,
        "symbols": {
            "XAUUSD_i": {
                **xau_i,
                "presence": xau_i.get("existence"),
            },
            "XAUUSD": {
                **xau,
                "presence": xau.get("existence"),
            },
        },
        "m5": _dataset_summary(collect_m5, m5_path),
        "targets": {
            "minimum_days": MIN_DAYS,
            "preferred_days": TARGET_DAYS,
            "minimum_60d_met": bool(days >= MIN_DAYS),
            "preferred_180d_met": bool(days >= TARGET_DAYS),
            "obtained_days": days,
        },
        "coverage": {
            "m5": m5_audit,
            "strategy_windows": windows,
            "coverage_pct_24x7": (m5_audit or {}).get("coverage_pct_24x7"),
            "coverage_pct_weekday_24h": (m5_audit or {}).get("coverage_pct_weekday_24h"),
        },
        "gaps": (m5_audit or {}).get("gap_classification") or {},
        "bid_ask": {
            "path": PHASE37_BIDASK if (root / PHASE37_BIDASK).is_file() else None,
            "status": bidask_stats.get("status"),
            "grade": bidask_stats.get("grade"),
            "not_proxy": True,
            "not_modeled": True,
            "proxy_not_relabeled_observed": True,
            "coverage_note": (
                f"OBSERVED ticks n={bidask_stats.get('n')} over bounded lookback"
                if bidask_stats.get("available")
                else "NOT_OBSERVED — no genuine historical Bid/Ask collected this run"
            ),
            "stats": bidask_stats if bidask_stats.get("available") else None,
        },
        "m15": _dataset_summary(collect_m15, PHASE37_M15 if (root / PHASE37_M15).is_file() else None),
        "m1": _dataset_summary(collect_m1, PHASE37_M1 if (root / PHASE37_M1).is_file() else None),
        "ticks": {
            "path": PHASE37_TICKS if (root / PHASE37_TICKS).is_file() else None,
            "status": collect_ticks.get("status"),
            "rows": collect_ticks.get("rows") or 0,
            "partial": bool(collect_ticks.get("partial")),
            "resource_bound": bool(collect_ticks.get("resource_bound")),
            "error": collect_ticks.get("error"),
        },
        "fingerprints": {
            "phase28_m5_file": frozen_fp,
            "phase28_m5_content": frozen_content,
            "phase28_m5_unchanged": fp_after == frozen_fp == EXPECTED_CANONICAL_FINGERPRINT,
            "phase37_m5_file": phase37_file_fp,
            "phase37_m5_content": phase37_content_fp,
            "reused_phase28_fingerprint": reused_phase28,
            "spec": {
                "algorithm": "SHA256",
                "file": "sha256 of parquet bytes",
                "content": "sha256 of UTC timestamp_ns,open,high,low,close,volume CSV",
            },
        },
        "dataset_binding": {
            "canonical_symbol": CANONICAL_SYMBOL,
            "dataset_symbol_map": {},
            "empty_map": True,
            "xauusd_merged": False,
            "xauusd_renamed": False,
            "silent_xauusd_mapping": False,
            "m5": binding.to_dict(),
            "logical_xauusd_used": False,
        },
        "provenance": {
            "symbol": CANONICAL_SYMBOL,
            "timeframe": "M5",
            "source": "mt5.copy_rates_from_pos attach-only" if attached else "not collected",
            "broker": session.get("broker"),
            "server": session.get("server"),
            "environment": session.get("environment"),
            "retrieval_timestamp_utc": session.get("retrieval_timestamp_utc"),
            "terminal_path": session.get("path"),
            "terminal_build": session.get("build"),
            "row_count": collect_m5.get("rows") or 0,
            "coverage": m5_audit,
            "gap_classification": (m5_audit or {}).get("gap_classification"),
            "fingerprint": phase37_file_fp,
            "content_hash": phase37_content_fp,
            "columns": (m5_audit or {}).get("columns"),
            "timezone": "UTC",
            "limitations": limitations,
        },
        "limitations": limitations,
        "wrote": wrote,
        "collection": {
            "m5": collect_m5,
            "m15": {k: v for k, v in collect_m15.items() if k != "frame"},
            "m1": {k: v for k, v in collect_m1.items() if k != "frame"},
            "ticks": {k: v for k, v in collect_ticks.items() if k != "frame"},
            "mt5_started_by_script": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_accessed": False,
        },
        "datasets_changed": fp_after != frozen_fp,
        "immutability_issues": issues,
        "immutability_ok": ok_immut and fp_after == frozen_fp,
        "canonical_fingerprint_before": frozen_fp,
        "canonical_fingerprint_after": fp_after,
        "reproducibility": {
            "data_fingerprint": frozen_fp,
            "output_fingerprint": _stable_hash(
                {
                    "status": status,
                    "terminal": session.get("status"),
                    "m5_rows": collect_m5.get("rows") or 0,
                    "m5_days": days,
                }
            ),
        },
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "CANONICAL_M5_OVERWRITTEN": False,
            "SILENT_XAUUSD_MAP": False,
            "PRODUCTION_CHANGED": False,
            "STRATEGY_EVALUATED": False,
            "PHASE_38_STARTED": False,
        },
        "phase_38_started": False,
        "next_step": "STOP. Do not start Phase 38. Do not run strategy evaluation. Do not optimize.",
    }
    _write_json(root / PHASE37_JSON, payload)
    _write_markdown(root, payload)
    _patch_truth_docs(root, status=status, terminal_status=str(session.get("status") or BLOCKED))
    if file_fingerprint(root / CANONICAL_PARQUET) != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Phase 37 mutated the frozen canonical M5 parquet")
    return payload


if __name__ == "__main__":
    run_phase37_collection()
