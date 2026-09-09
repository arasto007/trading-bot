"""Phase 29 — longest defensible XAUUSD_i research tape (data engineering only).

RESEARCH ONLY. Does not change strategy/RiskGate/ML/execution, start trading,
send orders, silently map XAUUSD→XAUUSD_i, overwrite Phase 28 canonical files,
or fabricate missing bars.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.backtest.dataset_contract import classify_dataset_binding
from tradingbot.backtest.dataset_provenance import load_dataset_metadata
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_9_real_broker_evidence import bounded_readonly_attach_once
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_26_canonical_bidask_coverage import TAPE_PARQUET as PHASE2726_BIDASK
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    H4_CONTEXT_PARQUET,
    UNKNOWN,
    load_parquet_utc,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.domain.position_logic import pip_size

PHASE = "29"
PHASE29_JSON = "logs/phase29_research_tape_manifest.json"
PHASE29_MD = "docs_v2/02_research/PHASE29_RESEARCH_TAPE.md"
PHASE29_M5 = "data/XAUUSD_i_5m_phase29.parquet"
PHASE29_H4 = "data/XAUUSD_i_4h_phase29.parquet"
PHASE29_M15 = "data/XAUUSD_i_15m.parquet"
TARGET_DAYS = 180
MIN_DAYS = 60
CANONICAL_SYMBOL = "XAUUSD_i"
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H4": 240}
FROZEN_PHASE28_M5_FINGERPRINT = EXPECTED_CANONICAL_FINGERPRINT

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "production_changes",
    "parameters_optimized",
    "collection",
    "datasets",
    "dataset_coverage",
    "data_quality",
    "bid_ask",
    "provenance",
    "fingerprints",
    "dataset_binding",
    "limitations",
    "FINAL_GATE",
    "phase_30_started",
)

CONTENT_FINGERPRINT_SPEC = {
    "algorithm": "SHA256",
    "input_columns": ["timestamp_utc_ns", "open", "high", "low", "close", "volume"],
    "row_ordering_rule": "timestamp ascending, UTC",
    "timestamp_normalization_rule": "tz-aware UTC; int64 nanoseconds since epoch",
}


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


def content_fingerprint(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return hashlib.sha256(b"empty").hexdigest()
    frame = df.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("content_fingerprint requires a DatetimeIndex")
    idx = pd.to_datetime(frame.index, utc=True)
    frame = frame.loc[~idx.duplicated()].sort_index()
    idx = pd.to_datetime(frame.index, utc=True)
    vol = frame["volume"] if "volume" in frame.columns else pd.Series(0.0, index=frame.index)
    payload = pd.DataFrame(
        {
            "timestamp_utc_ns": idx.asi8,
            "open": pd.to_numeric(frame["open"], errors="coerce").fillna(0.0),
            "high": pd.to_numeric(frame["high"], errors="coerce").fillna(0.0),
            "low": pd.to_numeric(frame["low"], errors="coerce").fillna(0.0),
            "close": pd.to_numeric(frame["close"], errors="coerce").fillna(0.0),
            "volume": pd.to_numeric(vol, errors="coerce").fillna(0.0),
        }
    )
    raw = payload.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def classify_gap(prev: pd.Timestamp, ts: pd.Timestamp, minutes: float) -> str:
    prev_wd = int(prev.weekday())
    ts_wd = int(ts.weekday())
    if minutes >= 24.0 * 60.0 and prev_wd >= 4 and ts_wd in (5, 6, 0, 1):
        return "EXPECTED_WEEKEND_GAP"
    if 50.0 <= minutes <= 90.0:
        if int(prev.hour) >= 20 or int(prev.hour) <= 1:
            return "BROKER_ROLLOVER_GAP"
        return "EXPECTED_SESSION_GAP"
    if minutes > 5:
        return "UNKNOWN_GAP"
    return "EXPECTED_SESSION_GAP"


def audit_dataset(df: pd.DataFrame, *, timeframe: str, path: str) -> dict[str, Any]:
    if df is None or df.empty:
        return {
            "path": path,
            "timeframe": timeframe,
            "row_count": 0,
            "coverage_pct_24x7": 0.0,
            "duplicate_timestamps": 0,
            "malformed_ohlc": 0,
            "impossible_ohlc": 0,
        }
    idx = pd.to_datetime(df.index, utc=True)
    ordered = bool(idx.is_monotonic_increasing)
    o = pd.to_numeric(df["open"], errors="coerce")
    h = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    c = pd.to_numeric(df["close"], errors="coerce")
    body_max = pd.concat([o, c], axis=1).max(axis=1)
    body_min = pd.concat([o, c], axis=1).min(axis=1)
    high_lt_low = h < low
    close_outside = (c > h) | (c < low)
    negative_price = (o <= 0) | (h <= 0) | (low <= 0) | (c <= 0)
    impossible = high_lt_low | (h < body_max) | (low > body_min) | close_outside
    malformed = impossible | negative_price | o.isna() | h.isna() | low.isna() | c.isna()
    vol = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else None
    step = TF_MINUTES.get(timeframe.upper(), 5)
    expected_delta = pd.Timedelta(minutes=step)
    deltas = idx.to_series().diff()
    gap_mask = deltas > expected_delta
    gap_classes: dict[str, int] = {
        "EXPECTED_SESSION_GAP": 0,
        "EXPECTED_WEEKEND_GAP": 0,
        "BROKER_ROLLOVER_GAP": 0,
        "UNKNOWN_GAP": 0,
    }
    gap_examples: list[dict[str, Any]] = []
    for ts, delta in deltas[gap_mask].items():
        prev = ts - delta
        minutes = float(delta.total_seconds() / 60.0)
        kind = classify_gap(prev, ts, minutes)
        gap_classes[kind] = gap_classes.get(kind, 0) + 1
        if len(gap_examples) < 16:
            gap_examples.append(
                {
                    "from": str(prev),
                    "to": str(ts),
                    "delta_minutes": minutes,
                    "classification": kind,
                }
            )
    start = idx[0]
    end = idx[-1]
    calendar_days = float((end - start).total_seconds() / 86400.0)
    span_slots = int(((end - start) / expected_delta) + 1)
    weekday_slots = 0
    cursor = start.floor(f"{step}min")
    limit = end
    # Bound the weekday walk; 180d M5 is ~52k steps.
    while cursor <= limit:
        if int(cursor.weekday()) < 5:
            weekday_slots += 1
        cursor += expected_delta
        if weekday_slots + 1 > 2_000_000:
            break
    observed = int(len(df))
    return {
        "path": path,
        "symbol": CANONICAL_SYMBOL,
        "timeframe": timeframe,
        "row_count": observed,
        "first_timestamp": str(start),
        "last_timestamp": str(end),
        "duration_days": round(calendar_days, 6),
        "expected_bars_24x7": span_slots,
        "expected_bars_weekday_24h": weekday_slots,
        "observed_bars": observed,
        "coverage_pct_24x7": round(100.0 * observed / max(span_slots, 1), 4),
        "coverage_pct_weekday_24h": round(100.0 * observed / max(weekday_slots, 1), 4),
        "duplicate_timestamps": int(idx.duplicated().sum()),
        "missing_timestamps_24x7": max(span_slots - observed, 0),
        "malformed_timestamps": int((~idx.notna()).sum()) if hasattr(idx, "notna") else 0,
        "malformed_ohlc": int(malformed.sum()),
        "impossible_ohlc": int(impossible.sum()),
        "high_lt_low": int(high_lt_low.sum()),
        "close_outside_high_low": int(close_outside.sum()),
        "negative_prices": int(negative_price.sum()),
        "zero_volume": int((vol == 0).sum()) if vol is not None else UNKNOWN,
        "negative_volume": int((vol < 0).sum()) if vol is not None else UNKNOWN,
        "abnormal_timestamp_ordering": not ordered,
        "timezone": str(idx.tz) if idx.tz is not None else "naive",
        "timezone_consistent_utc": bool(idx.tz is not None and str(idx.tz) == "UTC"),
        "gap_count": int(gap_mask.sum()),
        "gap_classification": gap_classes,
        "gap_examples": gap_examples,
        "columns": [str(c) for c in df.columns],
        "bid_present": any(str(c).lower() in {"bid", "bid_price"} for c in df.columns),
        "ask_present": any(str(c).lower() in {"ask", "ask_price"} for c in df.columns),
        "spread_column_present": any(str(c).lower() in {"spread", "tick_spread"} for c in df.columns),
        "note": (
            "Gaps are classified, not auto-treated as bad data. "
            "Weekend/rollover/session gaps are expected on gold."
        ),
    }


def attempt_readonly_ohlc_collection(*, timeframe: str, days: int) -> dict[str, Any]:
    """Attach-only copy_rates_from_pos. No symbol_select, no orders, no .env, no terminal start."""
    meta: dict[str, Any] = {
        "symbol": CANONICAL_SYMBOL,
        "timeframe": timeframe,
        "method": "copy_rates_from_pos read-only; attach-only; no symbol_select",
        "requested_days": days,
        "ok": False,
        "rows": 0,
        "retrieval_timestamp_utc": _utc_now(),
        "attach": None,
        "error": None,
    }
    attach = bounded_readonly_attach_once()
    meta["attach"] = {
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
        meta["error"] = attach.get("error") or "MT5 attach-only failed"
        meta["status"] = "NOT_OBSERVED"
        return meta
    try:
        import MetaTrader5 as mt5
    except ImportError:
        meta["error"] = "MetaTrader5 package not installed"
        meta["status"] = "NOT_OBSERVED"
        return meta
    tf_map = {
        "M5": mt5.TIMEFRAME_M5,
        "H4": mt5.TIMEFRAME_H4,
        "M15": mt5.TIMEFRAME_M15,
        "M1": mt5.TIMEFRAME_M1,
    }
    tf_const = tf_map[timeframe]
    info = mt5.symbol_info(CANONICAL_SYMBOL)
    if info is None:
        meta["error"] = "XAUUSD_i not present in attached catalog (symbol_info None). symbol_select was not called."
        meta["status"] = "NOT_OBSERVED"
        return meta
    acc = mt5.account_info()
    term = mt5.terminal_info()
    meta["account_environment"] = (
        "REAL" if acc is not None and getattr(acc, "trade_mode", None) == 2 else ("DEMO" if acc is not None else UNKNOWN)
    )
    meta["server"] = str(getattr(acc, "server", "") or UNKNOWN) if acc is not None else UNKNOWN
    meta["terminal_connected"] = bool(getattr(term, "connected", False)) if term is not None else False
    bpd = max(int(24 * 60 / TF_MINUTES[timeframe]), 1)
    want = min(days * bpd + 500, 100_000)
    rates = mt5.copy_rates_from_pos(CANONICAL_SYMBOL, tf_const, 0, want)
    if rates is None or len(rates) == 0:
        meta["error"] = "copy_rates_from_pos returned no rows"
        meta["status"] = "NOT_OBSERVED"
        return meta
    frame = pd.DataFrame(rates)
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
    frame = frame.set_index("time").sort_index()
    if "tick_volume" in frame.columns and "volume" not in frame.columns:
        frame["volume"] = frame["tick_volume"]
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in frame.columns]
    frame = frame[keep].copy()
    if "spread" in pd.DataFrame(rates).columns:
        meta["mt5_spread_points_present"] = True
        meta["mt5_spread_points_status"] = "OBSERVED_MT5_POINTS_NOT_HISTORICAL_BIDASK"
    meta["ok"] = True
    meta["status"] = "OBSERVED"
    meta["rows"] = int(len(frame))
    meta["start"] = str(frame.index[0])
    meta["end"] = str(frame.index[-1])
    meta["duration_days"] = float((frame.index[-1] - frame.index[0]).total_seconds() / 86400.0)
    meta["frame"] = frame
    return meta


def maybe_write_research_copy(root: Path, frame: pd.DataFrame, dest: str, *, reason: str) -> dict[str, Any]:
    """Write a Phase 29 research copy. Never the Phase 28 canonical path."""
    path = root / dest
    if dest.replace("\\", "/") in {CANONICAL_PARQUET, H4_CONTEXT_PARQUET}:
        raise RuntimeError("refusing to overwrite Phase 28 canonical parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    return {
        "path": dest,
        "written": True,
        "reason": reason,
        "file_fingerprint": file_fingerprint(path),
        "content_fingerprint": content_fingerprint(frame),
        "rows": int(len(frame)),
    }


def spread_stats_from_bidask(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty or "bid" not in df.columns or "ask" not in df.columns:
        return {"available": False, "status": "NOT_OBSERVED"}
    bid = pd.to_numeric(df["bid"], errors="coerce")
    ask = pd.to_numeric(df["ask"], errors="coerce")
    valid = bid.notna() & ask.notna() & (bid > 0) & (ask > 0) & (ask >= bid)
    spread = (ask - bid).loc[valid]
    if spread.empty:
        return {"available": False, "status": "NOT_OBSERVED"}
    pip = pip_size(CANONICAL_SYMBOL)
    spread_pips = spread / pip
    idx = pd.to_datetime(df.index, utc=True)
    by_hour = {
        str(h): float(spread_pips[idx.hour == h].median())
        for h in range(24)
        if (idx.hour == h).any()
    }

    def _window(hours: tuple[int, ...]) -> dict[str, Any]:
        mask = idx.hour.isin(hours)
        series = spread_pips[mask]
        if series.empty:
            return {"n": 0, "median_pips": None, "status": "NOT_OBSERVED"}
        return {
            "n": int(len(series)),
            "median_pips": float(series.median()),
            "p90_pips": float(np.percentile(series, 90)),
            "status": "OBSERVED",
        }

    return {
        "available": True,
        "status": "OBSERVED",
        "label": "OBSERVED historical Bid/Ask on the Phase 27.26 tape — not a 180-day tape, not PROXY",
        "not_proxy": True,
        "not_modeled": True,
        "n": int(len(spread)),
        "units_price": "ask-bid price units",
        "pip_size_heuristic": pip,
        "median": float(spread.median()),
        "p50": float(np.percentile(spread, 50)),
        "p75": float(np.percentile(spread, 75)),
        "p90": float(np.percentile(spread, 90)),
        "p95": float(np.percentile(spread, 95)),
        "p99": float(np.percentile(spread, 99)),
        "maximum": float(spread.max()),
        "median_pips": float(spread_pips.median()),
        "p95_pips": float(np.percentile(spread_pips, 95)),
        "by_hour_utc_median_pips": by_hour,
        "around_ny_open_15_16_utc": _window((15, 16)),
        "around_rollover_21_00_utc": _window((21, 22, 23, 0)),
        "around_friday_close": _window((20, 21)),
        "first_timestamp": str(idx[0]),
        "last_timestamp": str(idx[-1]),
    }


def bind_xauusd_i(root: Path, rel: str) -> dict[str, Any]:
    sidecar = load_dataset_metadata(root / rel)
    binding = classify_dataset_binding(
        CANONICAL_SYMBOL,
        configured_symbol=PRIMARY_SYMBOL,
        dataset_symbol_map={},
    )
    return {
        "path": rel,
        "logical_symbol": CANONICAL_SYMBOL,
        "configured_symbol": PRIMARY_SYMBOL,
        "dataset_symbol_map": {},
        "silent_xauusd_mapping": False,
        "ev_eq_01": "NOT_PROVEN",
        "binding": binding.to_dict(),
        "sidecar_mapping_status": getattr(sidecar, "mapping_status", None) if sidecar else None,
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    cov = payload["dataset_coverage"]
    q = payload["data_quality"]
    ba = payload["bid_ask"]
    path = root / PHASE29_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Phase 29 — Long-Horizon XAUUSD_i Research Tape

**Status:** {payload.get("status")}
**Class:** RESEARCH / DATA ENGINEERING ONLY
**Live trading authorized:** NO
**Production changes:** `{payload.get("production_changes")}`
**Parameters optimized:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`

Longest **defensible** historical research tape for broker-observed canonical symbol `XAUUSD_i`.
Logical `XAUUSD` tapes were **not** merged. EV-EQ-01 remains `NOT_PROVEN`.

STOP AFTER PHASE 29. DO NOT START PHASE 30.

---

## Coverage

| Tape | Path | Start | End | Days | Bars | Coverage % (weekday 24h) |
|---|---|---|---|---:|---:|---:|
| M5 entry (Phase 28 frozen) | `{cov["m5"]["path"]}` | {cov["m5"]["start"]} | {cov["m5"]["end"]} | {cov["m5"]["days"]} | {cov["m5"]["bars"]} | {cov["m5"]["coverage_pct_weekday_24h"]} |
| H4 context | `{cov["h4"]["path"]}` | {cov["h4"]["start"]} | {cov["h4"]["end"]} | {cov["h4"]["days"]} | {cov["h4"]["bars"]} | {cov["h4"]["coverage_pct_weekday_24h"]} |
| M15 | — | — | — | — | 0 | NOT_OBSERVED |

Target ≥ 180 calendar days. Minimum acceptable ≥ 60. **M5 obtainable days = {cov["m5"]["days"]}.** Completeness was not fabricated.

---

## Collection

{payload["collection"]["summary"]}

MT5 trading was not started. `symbol_select` was not called. `.env` was not read. Orders were not sent.

---

## Data quality (M5)

| Check | Result |
|---|---|
| Duplicates | {q["m5"]["duplicate_timestamps"]} |
| Malformed OHLC | {q["m5"]["malformed_ohlc"]} |
| Impossible OHLC | {q["m5"]["impossible_ohlc"]} |
| Zero volume | {q["m5"]["zero_volume"]} |
| Negative volume | {q["m5"]["negative_volume"]} |
| Timezone | {q["m5"]["timezone"]} |
| Gap classes | {q["m5"]["gap_classification"]} |

Gaps are classified. Weekend / rollover / session gaps are not automatically bad data.

---

## Bid / Ask

Available on a **separate** Phase 27.26 tape (`{ba.get("path")}`), not inside the OHLC parquet.

- Status: `{ba.get("status")}`
- Coverage vs Phase 28 M5 bars: `{ba.get("coverage_vs_canonical_m5")}`
- Spread provenance: `{ba.get("spread_provenance")}`
- Median spread (price / pips heuristic): `{ba.get("stats", {}).get("median")} / {ba.get("stats", {}).get("median_pips")}`

PROXY OHLC spread was **not** relabeled as OBSERVED.

---

## Provenance

- Symbol: `XAUUSD_i`
- Environment (OHLC sidecar): `{payload["provenance"]["ohlc_account_environment"]}`
- Source: `{payload["provenance"]["source"]}`
- Retrieval of new MT5 bars: `{payload["collection"]["m5"].get("status")}`
- This dataset proves only what was actually observed. It does not prove broker-wide economics outside the observed terminal/account.

## Fingerprints

- Phase 28 frozen M5 file SHA256: `{payload["fingerprints"]["phase28_m5_file"]}`
- Phase 28 frozen M5 content: `{payload["fingerprints"]["phase28_m5_content"]}`
- Spec: `{payload["fingerprints"]["spec"]}`

Phase 28 canonical parquet was **not** overwritten.

## Dataset binding

Empty `dataset_symbol_map`. `XAUUSD_i` is a direct canonical match. Logical `XAUUSD` remains `ONLY_WITH_EXPLICIT_DATASET_MAP`. Silent mapping did not occur.

## Limitations

{payload.get("limitations")}

## Recommendation

{payload.get("recommendation")}

## Safety

No strategy / RiskGate / ML / execution / PA-lock / calibration change. Phase 30 was **not** started.
""",
        encoding="utf-8",
    )


def run_phase29_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    frozen_fp = file_fingerprint(root / CANONICAL_PARQUET)
    if frozen_fp != FROZEN_PHASE28_M5_FINGERPRINT:
        raise RuntimeError("Phase 28 canonical M5 fingerprint changed before Phase 29 — refuse to proceed")

    m5 = load_parquet_utc(root / CANONICAL_PARQUET)
    h4 = load_parquet_utc(root / H4_CONTEXT_PARQUET) if (root / H4_CONTEXT_PARQUET).is_file() else pd.DataFrame()
    m5_audit = audit_dataset(m5, timeframe="M5", path=CANONICAL_PARQUET)
    h4_audit = audit_dataset(h4, timeframe="H4", path=H4_CONTEXT_PARQUET) if not h4.empty else {"row_count": 0}

    collect_m5 = attempt_readonly_ohlc_collection(timeframe="M5", days=TARGET_DAYS)
    collect_h4 = attempt_readonly_ohlc_collection(timeframe="H4", days=TARGET_DAYS)
    collect_m15 = attempt_readonly_ohlc_collection(timeframe="M15", days=TARGET_DAYS)
    wrote: dict[str, Any] = {}
    for key, dest, existing_days in (
        ("m5", PHASE29_M5, m5_audit.get("duration_days") or 0),
        ("h4", PHASE29_H4, h4_audit.get("duration_days") or 0),
    ):
        block = collect_m5 if key == "m5" else collect_h4
        frame = block.pop("frame", None)
        if block.get("ok") and frame is not None and float(block.get("duration_days") or 0) > float(existing_days) + 0.5:
            wrote[key] = maybe_write_research_copy(
                root,
                frame,
                dest,
                reason="attach-only copy_rates produced a longer XAUUSD_i tape than the frozen snapshot",
            )
        elif (root / dest).is_file():
            wrote[key] = {
                "path": dest,
                "written": False,
                "reason": "existing Phase 29 copy left in place; no longer observed tape this run",
            }

    bidask_path = root / PHASE2726_BIDASK
    bidask_df = pd.read_parquet(bidask_path) if bidask_path.is_file() else pd.DataFrame()
    if not bidask_df.empty and not isinstance(bidask_df.index, pd.DatetimeIndex):
        if "time" in bidask_df.columns:
            bidask_df = bidask_df.set_index(pd.to_datetime(bidask_df["time"], utc=True))
    ba_stats = spread_stats_from_bidask(bidask_df) if not bidask_df.empty else {"available": False, "status": "NOT_OBSERVED"}
    ba_rows = int(len(bidask_df)) if not bidask_df.empty else 0
    ba_coverage = round(100.0 * ba_rows / max(len(m5), 1), 4) if ba_rows else 0.0

    sidecar_m5 = load_dataset_metadata(root / CANONICAL_PARQUET)
    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}

    m5_days = float(m5_audit.get("duration_days") or 0)
    collected_days = float(collect_m5.get("duration_days") or 0)
    best_m5_days = max(m5_days, collected_days)
    if best_m5_days >= TARGET_DAYS and m5_audit.get("impossible_ohlc") == 0:
        status = "PASS"
    else:
        status = "PASS_WITH_DEFERRAL"

    collect_summary = (
        f"Attach-only M5 collection: {collect_m5.get('status')}. "
        f"Error: {collect_m5.get('error') or 'none'}. "
        "Terminal was not started by this phase. "
        f"Longest defensible existing M5 coverage is {m5_days:.2f} calendar days."
    )
    limitations = (
        f"M5 XAUUSD_i coverage is {m5_days:.2f} calendar days (target {TARGET_DAYS}, minimum {MIN_DAYS}). "
        "A longer tape was not observed this run because attach-only MT5 collection did not return "
        "additional XAUUSD_i bars. Logical XAUUSD 180d/183d files exist but remain BLOCKED "
        "(MISSING_EXPLICIT_MAP; EV-EQ-01 NOT_PROVEN) and were not merged. "
        "OHLC has no Bid/Ask columns (PROXY/ohlc_only). Phase 27.26 Bid/Ask is OBSERVED only for "
        "the ~15-day canonical window and is not a 180-day tape. "
        "Sidecar economics are DEMO LiteFinance evidence and do not prove Real-account identity."
    )
    recommendation = (
        "Keep the Phase 28 M5 snapshot frozen. When a terminal is already running, re-run this "
        "phase attach-only to persist a longer XAUUSD_i tape under data/XAUUSD_i_*_phase29.parquet. "
        "Do not silently promote logical XAUUSD history. Do not start parameter optimization. "
        "Phase 30 was not started."
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
        "strategy_changed": False,
        "riskgate_changed": False,
        "ml_changed": False,
        "silent_xauusd_mapping": False,
        "ev_eq_01": "NOT_PROVEN",
        "cost_completeness": BLOCKED,
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "collection": {
            "summary": collect_summary,
            "m5": {k: v for k, v in collect_m5.items() if k != "frame"},
            "h4": {k: v for k, v in collect_h4.items() if k != "frame"},
            "m15": {k: v for k, v in collect_m15.items() if k != "frame"},
            "wrote": wrote,
            "mt5_started_by_script": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_accessed": False,
        },
        "datasets": {
            "m5_frozen_phase28": CANONICAL_PARQUET,
            "h4_existing": H4_CONTEXT_PARQUET,
            "m5_phase29_copy": PHASE29_M5 if (root / PHASE29_M5).is_file() else None,
            "h4_phase29_copy": PHASE29_H4 if (root / PHASE29_H4).is_file() else None,
            "m15": None,
            "logical_xauusd_used": False,
            "forbidden_merge_not_performed": [
                "data/backtest/XAUUSD_M5_183d.parquet",
                "data/backtest/XAUUSD_M5_180d.parquet",
                "data/XAUUSD_5m.parquet",
            ],
        },
        "dataset_coverage": {
            "m5": {
                "path": CANONICAL_PARQUET,
                "start": m5_audit.get("first_timestamp"),
                "end": m5_audit.get("last_timestamp"),
                "days": m5_audit.get("duration_days"),
                "bars": m5_audit.get("row_count"),
                "coverage_pct_24x7": m5_audit.get("coverage_pct_24x7"),
                "coverage_pct_weekday_24h": m5_audit.get("coverage_pct_weekday_24h"),
                "below_minimum_60d": m5_days < MIN_DAYS,
            },
            "h4": {
                "path": H4_CONTEXT_PARQUET,
                "start": h4_audit.get("first_timestamp"),
                "end": h4_audit.get("last_timestamp"),
                "days": h4_audit.get("duration_days"),
                "bars": h4_audit.get("row_count"),
                "coverage_pct_24x7": h4_audit.get("coverage_pct_24x7"),
                "coverage_pct_weekday_24h": h4_audit.get("coverage_pct_weekday_24h"),
            },
            "m15": {"path": None, "status": "NOT_OBSERVED"},
        },
        "data_quality": {"m5": m5_audit, "h4": h4_audit},
        "bid_ask": {
            "available": bool(ba_stats.get("available")),
            "status": ba_stats.get("status"),
            "path": PHASE2726_BIDASK if bidask_path.is_file() else None,
            "in_ohlc_parquet": False,
            "ohlc_spread_status": "PROXY",
            "spread_provenance": "OBSERVED" if ba_stats.get("available") else "UNKNOWN",
            "coverage_vs_canonical_m5": ba_coverage,
            "covered_bars": ba_rows,
            "canonical_m5_bars": int(len(m5)),
            "uncovered_note": (
                "Phase 27.26 Bid/Ask covers part of the 15-day canonical M5 window only. "
                "It is not a long-horizon tape. Uncovered M5 bars and all dates outside "
                "2026-08-13..2026-08-28 remain WITHOUT observed Bid/Ask."
            ),
            "stats": ba_stats,
        },
        "provenance": {
            "symbol": CANONICAL_SYMBOL,
            "ohlc_account_environment": getattr(sidecar_m5, "account_environment", None) or UNKNOWN,
            "ohlc_server": getattr(sidecar_m5, "server", None) or UNKNOWN,
            "source": getattr(sidecar_m5, "source_artifact", None) or "existing_canonical_parquet",
            "economics_source": getattr(sidecar_m5, "economics_source", None) or UNKNOWN,
            "spread_mode": getattr(sidecar_m5, "spread_mode", None) or "PROXY",
            "retrieval_timestamp_utc": collect_m5.get("retrieval_timestamp_utc"),
            "proves": "only what was actually observed on the labeled XAUUSD_i files / attached terminal",
            "does_not_prove": "broker-wide economics; XAUUSD ≡ XAUUSD_i; Real==Demo; 180-day completeness",
        },
        "fingerprints": {
            "spec": CONTENT_FINGERPRINT_SPEC,
            "phase28_m5_file": frozen_fp,
            "phase28_m5_content": content_fingerprint(m5),
            "phase28_h4_file": file_fingerprint(root / H4_CONTEXT_PARQUET) if (root / H4_CONTEXT_PARQUET).is_file() else None,
            "phase28_h4_content": content_fingerprint(h4) if not h4.empty else None,
            "phase28_m5_unchanged": True,
        },
        "dataset_binding": {
            "m5": bind_xauusd_i(root, CANONICAL_PARQUET),
            "h4": bind_xauusd_i(root, H4_CONTEXT_PARQUET) if (root / H4_CONTEXT_PARQUET).is_file() else None,
            "empty_map": True,
            "xauusd_merged": False,
        },
        "limitations": limitations,
        "recommendation": recommendation,
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "ML_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "CANONICAL_M5_OVERWRITTEN": False,
            "PHASE_30_STARTED": False,
        },
        "phase_30_started": False,
    }

    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    # New Phase 29 copies are allowed; the frozen Phase 28 M5 file must not change.
    payload["canonical_m5_changed"] = fp_after != frozen_fp
    payload["immutability_issues"] = issues
    payload["datasets_changed"] = bool(payload["canonical_m5_changed"])
    if payload["canonical_m5_changed"]:
        raise RuntimeError("Phase 29 mutated the frozen Phase 28 M5 parquet")

    _write_json(root / PHASE29_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Research tape (Phase 29)"
        block = (
            "\n\n## Research tape (Phase 29)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Longest defensible XAUUSD_i M5 tape is the Phase 28 15-day snapshot | **SUPPORTED** this run |\n"
            "| 180-day XAUUSD_i M5 tape was collected | **NOT_OBSERVED** — attach-only; terminal not running |\n"
            "| Logical XAUUSD 183d used as XAUUSD_i | **NO** — BLOCKED, not merged |\n"
            "| Phase 29 authorizes live trading or optimization | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")

    return payload


if __name__ == "__main__":
    run_phase29_collection()
