"""Phase 115 — full-horizon non-OHLC data acquisition and ingestion.

RESEARCH / DATA ONLY. Ingests operator-local proven XAUUSD_i files.
Does not connect to MT5, read .env, download remotely, synthesize ticks,
or modify production. Does not start Phase 116 or implement an exit spec.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
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
    _parse_ts,
    _utc_now,
)
from tradingbot.backtest.phase68_exit_forensics import BAR_MINUTES, load_frozen_ohlc
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON
from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON
from tradingbot.backtest.phase82_profit_protection_design import REVERSAL_BARS
from tradingbot.backtest.phase106_non_ohlc_data_inventory import CANDIDATES
from tradingbot.backtest.phase114_non_ohlc_acquisition_contract import (
    CANONICAL_SYMBOL,
    H1_MINUTES,
    H4_MINUTES,
    LOGICAL_SYMBOL,
    M1_MINUTES,
    M15_MINUTES,
    NEWS_MINUTES_BEFORE,
    TZ,
)

PHASE = "115"
PHASE115_JSON = "logs/phase115_non_ohlc_data_acquisition.json"
PHASE115_MD = "docs/PHASE115_NON_OHLC_DATA_ACQUISITION.md"
RESEARCH_ROOT = "data/research/non_ohlc"
NORMALIZATION_VERSION = "phase115-v1"
BLOCKED = "BLOCKED"
EXPECTED_JSONL_SHA256 = "6f4ff0b6dae0d86974414f129f3c1e6009c21bcb285ad0c449d5033bda4ee17f"
PHASE40_TS = "2026-09-07T21:09:46Z"
N_EVENTS = 419
N_AMBIGUOUS_394 = 394
ACQ_START_ISO = "2023-02-26T15:40:00Z"
ACQ_END_ISO = "2026-09-07T20:10:00Z"
REJECT_SYMBOLS = frozenset({"XAUUSD", "GOLD", "GOLDUSD", "GOLD/USD", "XAU/USD"})
CHRONOLOGY_CLASSES = (
    "FAVORABLE_FIRST",
    "ADVERSE_FIRST",
    "SIMULTANEOUS_UNRESOLVED",
    "EXIT_WITHOUT_INTRABAR_RESOLUTION",
    "DATA_INSUFFICIENT",
)
QUALITY_CLASSES = ("COMPLETE", "PARTIAL", "INVALID", "MISSING")
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "PHASE115_STATUS",
    "ACQUISITION_STATUS",
    "INGESTION_STATUS",
    "DATA_QUALITY_STATUS",
    "PHASE116_READY",
    "coverage_matrix",
    "final_gate",
    "production_safety",
    "artifacts",
)

# Extra predeclared local paths (Phase 37 sidecars). Not a repository rediscovery.
EXTRA_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "id": "A_TICK_PHASE37",
        "category": "tick",
        "path": "data/XAUUSD_i_ticks_phase37.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "tick",
        "time_cols": ("time_msc", "time"),
    },
    {
        "id": "D_M1_PHASE37",
        "category": "m1",
        "path": "data/XAUUSD_i_m1_phase37.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "M1",
        "time_cols": ("time",),
    },
    {
        "id": "F_H1_CANONICAL_ABSENT",
        "category": "h1",
        "path": "data/XAUUSD_i_1h.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "H1",
        "time_cols": ("time",),
    },
    {
        "id": "I_NEWS_RESEARCH",
        "category": "news",
        "path": "data/research/non_ohlc/news/historical_calendar.parquet",
        "symbol": "calendar",
        "timeframe": "event",
        "time_cols": ("event_timestamp_utc",),
    },
)

NEWS_GENERATOR = "tradingbot/ml/data/news_calendar.py"


def iso_z(ts: datetime | pd.Timestamp | None) -> str | None:
    if ts is None or (isinstance(ts, float) and np.isnan(ts)):
        return None
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_xauusd_i(symbol: str | None = None, path: str | None = None) -> bool:
    """Accept only explicit XAUUSD_i identity. Generic XAUUSD/GOLD is rejected."""
    name = Path(path or "").name
    stem = Path(path or "").stem
    if symbol in REJECT_SYMBOLS:
        return False
    if symbol == CANONICAL_SYMBOL:
        return True
    if CANONICAL_SYMBOL in name or CANONICAL_SYMBOL in stem:
        return True
    blob = " ".join(x for x in (symbol or "", name, stem) if x)
    if LOGICAL_SYMBOL in blob:
        return False
    return False


def enforce_utc(ts: Any) -> pd.Timestamp | None:
    t = pd.to_datetime(ts, utc=True, errors="coerce")
    if pd.isna(t):
        return None
    t = pd.Timestamp(t)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t


def parse_tick_timestamps(df: pd.DataFrame) -> pd.Series:
    if "time_msc" in df.columns:
        raw = pd.to_numeric(df["time_msc"], errors="coerce")
        sample = raw.dropna()
        if len(sample):
            unit = "ms" if float(sample.iloc[0]) > 1e11 else "s"
            return pd.to_datetime(raw, unit=unit, utc=True, errors="coerce")
    for col in ("timestamp_utc", "time_utc", "time", "timestamp"):
        if col in df.columns:
            return pd.to_datetime(df[col], utc=True, errors="coerce")
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        else:
            idx = idx.tz_convert("UTC")
        return pd.Series(idx, index=df.index)
    return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")


def derive_spread(bid: Any, ask: Any) -> float | None:
    try:
        b = float(bid)
        a = float(ask)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(b) or not np.isfinite(a):
        return None
    return a - b


def validate_tick_frame(df: pd.DataFrame) -> dict[str, Any]:
    """Validate canonical tick rows. Does not interpolate or synthesize."""
    n = int(len(df))
    out: dict[str, Any] = {
        "n_rows": n,
        "invalid_rows": 0,
        "missing_bid_rows": 0,
        "missing_ask_rows": 0,
        "missing_both_rows": 0,
        "duplicate_timestamps": 0,
        "timezone_ambiguous": 0,
        "impossible_timestamps": 0,
        "ask_lt_bid": 0,
        "nonpositive": 0,
        "non_finite": 0,
        "out_of_order_rows": 0,
        "valid": False,
    }
    if n == 0:
        return out
    ts = df["timestamp_utc"] if "timestamp_utc" in df.columns else parse_tick_timestamps(df)
    bid = pd.to_numeric(df["bid"], errors="coerce") if "bid" in df.columns else pd.Series(np.nan, index=df.index)
    ask = pd.to_numeric(df["ask"], errors="coerce") if "ask" in df.columns else pd.Series(np.nan, index=df.index)
    missing_bid = bid.isna()
    missing_ask = ask.isna()
    out["missing_bid_rows"] = int(missing_bid.sum())
    out["missing_ask_rows"] = int(missing_ask.sum())
    out["missing_both_rows"] = int((missing_bid & missing_ask).sum())
    finite = bid.apply(lambda x: bool(np.isfinite(x)) if pd.notna(x) else False) & ask.apply(
        lambda x: bool(np.isfinite(x)) if pd.notna(x) else False
    )
    out["non_finite"] = int((~finite & ~(missing_bid | missing_ask)).sum()) if n else 0
    pos = (bid > 0) & (ask > 0)
    out["nonpositive"] = int(((~pos) & finite).sum())
    out["ask_lt_bid"] = int(((ask < bid) & finite).sum())
    bad_ts = ts.isna()
    out["timezone_ambiguous"] = int(bad_ts.sum())
    if hasattr(ts, "dt"):
        years = ts.dt.year
        out["impossible_timestamps"] = int(((years < 2000) | (years > 2030) | bad_ts).sum())
    ts_ok = ts.dropna()
    if len(ts_ok):
        out["duplicate_timestamps"] = int(ts_ok.duplicated().sum())
        deltas = ts_ok.sort_values().diff()
        out["out_of_order_rows"] = int((deltas < pd.Timedelta(0)).sum())
    invalid = (
        missing_bid
        | missing_ask
        | (~pos)
        | (ask < bid)
        | bad_ts
        | (~bid.apply(lambda x: bool(np.isfinite(x)) if pd.notna(x) else False))
        | (~ask.apply(lambda x: bool(np.isfinite(x)) if pd.notna(x) else False))
    )
    out["invalid_rows"] = int(invalid.sum())
    out["valid"] = out["invalid_rows"] < n and out["missing_bid_rows"] + out["missing_ask_rows"] < n
    return out


def is_weekend_gap(gap_start: pd.Timestamp, gap_end: pd.Timestamp | None = None) -> bool:
    """Gold weekend: Friday >= 21:00 UTC through Sunday. Not a weekday hole."""
    start = enforce_utc(gap_start)
    if start is None:
        return False
    dow = int(start.dayofweek)
    hour = int(start.hour)
    if dow in (5, 6):
        return True
    if dow == 4 and hour >= 21:
        return True
    if gap_end is not None:
        end = enforce_utc(gap_end)
        if end is not None and dow == 4 and int(end.dayofweek) in (5, 6, 0):
            return True
    return False


def gap_statistics(ts: pd.DatetimeIndex, weekday_threshold: timedelta | None = None) -> dict[str, Any]:
    weekday_threshold = weekday_threshold or timedelta(minutes=60)
    if ts is None or len(ts) < 2:
        return {
            "n_gaps": 0,
            "weekend_gaps": 0,
            "weekday_gaps": 0,
            "suspicious_gaps": 0,
            "max_gap_ms": None,
            "median_gap_ms": None,
            "p50_gap_ms": None,
            "p90_gap_ms": None,
            "p99_gap_ms": None,
        }
    ordered = pd.DatetimeIndex(pd.to_datetime(ts, utc=True)).sort_values()
    diffs = ordered.to_series().diff().dropna()
    ms = diffs.dt.total_seconds() * 1000.0
    weekend = weekday = suspicious = 0
    max_gap = None
    for start, delta in zip(ordered[:-1], diffs):
        end = start + delta
        if is_weekend_gap(start, end):
            weekend += 1
        elif delta >= weekday_threshold:
            weekday += 1
            if delta >= timedelta(hours=1):
                suspicious += 1
        if max_gap is None or delta > max_gap:
            max_gap = delta
    q = ms.quantile([0.5, 0.9, 0.99])
    return {
        "n_gaps": int(len(diffs)),
        "weekend_gaps": int(weekend),
        "weekday_gaps": int(weekday),
        "suspicious_gaps": int(suspicious),
        "max_gap_ms": None if max_gap is None else int(max_gap.total_seconds() * 1000),
        "median_gap_ms": None if ms.empty else float(ms.median()),
        "p50_gap_ms": None if ms.empty else float(q.loc[0.5]),
        "p90_gap_ms": None if ms.empty else float(q.loc[0.9]),
        "p99_gap_ms": None if ms.empty else float(q.loc[0.99]),
    }


def asof_tick_index(ts_ns: np.ndarray, state_ns: int) -> int:
    """Last tick with timestamp <= state. Never a future tick. -1 if none."""
    if ts_ns.size == 0:
        return -1
    i = int(np.searchsorted(ts_ns, state_ns, side="right") - 1)
    if i < 0:
        return -1
    if int(ts_ns[i]) > state_ns:
        return -1
    return i


def last_closed_bar_index(opens_ns: np.ndarray, duration_ns: int, state_ns: int) -> int:
    """Last bar with open + duration <= state. Forming bar is excluded."""
    if opens_ns.size == 0:
        return -1
    close_ns = opens_ns + duration_ns
    i = int(np.searchsorted(close_ns, state_ns, side="right") - 1)
    if i < 0:
        return -1
    if int(close_ns[i]) > state_ns:
        return -1
    return i


def classify_intrabar_order(
    side: str,
    entry: float,
    tick_ts: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    exit_ns: int | None = None,
) -> dict[str, Any]:
    """Research-only reconstruction. Does not change production execution.

    BUY favorable: ask > entry (upside print). BUY adverse: bid < entry.
    SELL favorable: bid < entry. SELL adverse: ask > entry.
    Same-timestamp fav+adv is SIMULTANEOUS_UNRESOLVED. Not assumed favorable-first.
    """
    buy = str(side).upper() in {"BUY", "1", "LONG"}
    empty = {
        "class": "DATA_INSUFFICIENT",
        "first_favorable_tick_utc": None,
        "first_adverse_tick_utc": None,
        "same_timestamp_ambiguous": False,
        "n_ticks": int(len(tick_ts)),
        "bid_ask_sufficient_documented": True,
        "semantics": {
            "long_favorable": "ask > entry",
            "long_adverse": "bid < entry",
            "short_favorable": "bid < entry",
            "short_adverse": "ask > entry",
            "production_execution_unchanged": True,
        },
    }
    if len(tick_ts) == 0 or entry is None or not np.isfinite(entry):
        return empty
    if buy:
        fav = ask > entry
        adv = bid < entry
    else:
        fav = bid < entry
        adv = ask > entry
    fav_i = int(np.argmax(fav)) if fav.any() else None
    adv_i = int(np.argmax(adv)) if adv.any() else None
    if fav_i is not None and not fav[fav_i]:
        fav_i = None
    if adv_i is not None and not adv[adv_i]:
        adv_i = None
    t_fav = int(tick_ts[fav_i]) if fav_i is not None else None
    t_adv = int(tick_ts[adv_i]) if adv_i is not None else None
    empty["first_favorable_tick_utc"] = iso_z(pd.Timestamp(t_fav, unit="ns", tz="UTC")) if t_fav is not None else None
    empty["first_adverse_tick_utc"] = iso_z(pd.Timestamp(t_adv, unit="ns", tz="UTC")) if t_adv is not None else None
    if t_fav is None and t_adv is None:
        empty["class"] = "EXIT_WITHOUT_INTRABAR_RESOLUTION" if exit_ns is not None else "DATA_INSUFFICIENT"
        return empty
    if t_fav is not None and t_adv is not None and t_fav == t_adv:
        empty["class"] = "SIMULTANEOUS_UNRESOLVED"
        empty["same_timestamp_ambiguous"] = True
        return empty
    if t_fav is not None and (t_adv is None or t_fav < t_adv):
        empty["class"] = "FAVORABLE_FIRST"
        return empty
    if t_adv is not None and (t_fav is None or t_adv < t_fav):
        empty["class"] = "ADVERSE_FIRST"
        return empty
    empty["class"] = "SIMULTANEOUS_UNRESOLVED"
    empty["same_timestamp_ambiguous"] = True
    return empty


def validate_ohlc_frame(df: pd.DataFrame) -> dict[str, Any]:
    n = int(len(df))
    out = {"n_rows": n, "invalid_count": 0, "duplicate_count": 0, "valid": n > 0}
    if n == 0:
        return out
    ts = df["timestamp_utc"] if "timestamp_utc" in df.columns else parse_tick_timestamps(df)
    out["duplicate_count"] = int(ts.duplicated().sum())
    o = pd.to_numeric(df.get("open"), errors="coerce")
    h = pd.to_numeric(df.get("high"), errors="coerce")
    l = pd.to_numeric(df.get("low"), errors="coerce")
    c = pd.to_numeric(df.get("close"), errors="coerce")
    invalid = (
        ts.isna()
        | o.isna()
        | h.isna()
        | l.isna()
        | c.isna()
        | (h < l)
        | (h < o)
        | (h < c)
        | (l > o)
        | (l > c)
        | (o <= 0)
        | (h <= 0)
        | (l <= 0)
        | (c <= 0)
    )
    out["invalid_count"] = int(invalid.sum())
    out["valid"] = out["invalid_count"] < n
    return out


def _bar_opens(df: pd.DataFrame) -> pd.DatetimeIndex:
    if "timestamp_utc" in df.columns:
        ts = pd.to_datetime(df["timestamp_utc"], utc=True)
    elif "time" in df.columns:
        ts = pd.to_datetime(df["time"], utc=True)
    elif isinstance(df.index, pd.DatetimeIndex):
        ts = df.index
        ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
    else:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.DatetimeIndex(ts)


def normalize_ohlc(df: pd.DataFrame, source: str, symbol: str) -> pd.DataFrame:
    ts = _bar_opens(df)
    vol = df["volume"] if "volume" in df.columns else pd.Series(np.nan, index=df.index)
    out = pd.DataFrame(
        {
            "timestamp_utc": ts,
            "open": pd.to_numeric(df["open"], errors="coerce") if "open" in df.columns else np.nan,
            "high": pd.to_numeric(df["high"], errors="coerce") if "high" in df.columns else np.nan,
            "low": pd.to_numeric(df["low"], errors="coerce") if "low" in df.columns else np.nan,
            "close": pd.to_numeric(df["close"], errors="coerce") if "close" in df.columns else np.nan,
            "volume": pd.to_numeric(vol, errors="coerce"),
        }
    )
    out.attrs["source"] = source
    out.attrs["symbol"] = symbol
    out.attrs["timezone"] = TZ
    out.attrs["normalization_version"] = NORMALIZATION_VERSION
    return out.sort_values("timestamp_utc").reset_index(drop=True)


def normalize_ticks(df: pd.DataFrame, source: str, symbol: str) -> pd.DataFrame:
    ts = parse_tick_timestamps(df)
    bid = pd.to_numeric(df["bid"], errors="coerce") if "bid" in df.columns else pd.Series(np.nan, index=df.index)
    ask = pd.to_numeric(df["ask"], errors="coerce") if "ask" in df.columns else pd.Series(np.nan, index=df.index)
    last = pd.to_numeric(df["last"], errors="coerce") if "last" in df.columns else pd.Series(np.nan, index=df.index)
    vol = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else pd.Series(np.nan, index=df.index)
    flags = df["flags"] if "flags" in df.columns else pd.Series([None] * len(df), index=df.index)
    out = pd.DataFrame(
        {
            "timestamp_utc": ts,
            "bid": bid,
            "ask": ask,
            "last": last,
            "volume": vol,
            "flags": flags,
            "source": source,
            "symbol": symbol,
            "spread": ask - bid,
        }
    )
    out = out.dropna(subset=["timestamp_utc"])
    out = out.sort_values("timestamp_utc")
    out = out.drop_duplicates(subset=["timestamp_utc", "bid", "ask"], keep="first")
    out.attrs["source"] = source
    out.attrs["symbol"] = symbol
    out.attrs["timezone"] = TZ
    out.attrs["normalization_version"] = NORMALIZATION_VERSION
    return out.reset_index(drop=True)


def window_bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(ACQ_START_ISO)
    end = pd.Timestamp(ACQ_END_ISO)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    return start, end


def trading_day_counts(ts: pd.DatetimeIndex) -> dict[str, Any]:
    if ts is None or len(ts) == 0:
        return {"calendar_days": 0, "active_trading_days": 0}
    t = pd.DatetimeIndex(pd.to_datetime(ts, utc=True))
    days = t.normalize().unique()
    active = [d for d in days if int(d.dayofweek) < 5]
    return {"calendar_days": int(len(days)), "active_trading_days": int(len(active))}


def quality_class(*, verified: bool, n_rows: int, event_cov: int, invalid: bool) -> str:
    if invalid or not verified:
        return "INVALID" if (n_rows > 0 and not verified) or invalid else "MISSING"
    if n_rows <= 0:
        return "MISSING"
    if event_cov >= N_EVENTS:
        return "COMPLETE"
    if event_cov > 0:
        return "PARTIAL"
    return "PARTIAL" if n_rows > 0 else "MISSING"


def coverage_row(
    source: str,
    timeframe: str,
    symbol: str,
    requested_start: str,
    requested_end: str,
    actual_start: str | None,
    actual_end: str | None,
    row_count: int,
    event_count: int,
    lifecycle_count: int,
    weekday_gap_count: int,
    duplicate_count: int,
    invalid_count: int,
    causal_ready: bool,
    verified: bool,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "source": source,
        "timeframe": timeframe,
        "symbol": symbol,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "actual_start": actual_start,
        "actual_end": actual_end,
        "row_count": row_count,
        "event_count": N_EVENTS,
        "event_coverage_count": event_count,
        "event_coverage_ratio": event_count / N_EVENTS if N_EVENTS else 0.0,
        "lifecycle_coverage_count": lifecycle_count,
        "lifecycle_coverage_ratio": lifecycle_count / N_EVENTS if N_EVENTS else 0.0,
        "weekday_gap_count": weekday_gap_count,
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "causal_ready": causal_ready,
        "xauusd_i_verified": verified,
        "status": status,
    }
    if extra:
        row.update(extra)
    return row


def _write_meta(path: Path, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


def _discover_sources(root: Path) -> list[dict[str, Any]]:
    specs = list(CANDIDATES) + list(EXTRA_CANDIDATES)
    seen: set[str] = set()
    rows = []
    acq_start, acq_end = window_bounds()
    for spec in specs:
        path = spec["path"]
        if path in seen:
            continue
        seen.add(path)
        p = root / path
        exists = p.is_file()
        symbol = spec.get("symbol")
        verified = verify_xauusd_i(symbol=symbol, path=path)
        if spec.get("symbol_binding") == "EV-EQ-01_NOT_PROVEN":
            verified = False
        if spec["category"] == "news":
            verified = False
        cols: list[str] = []
        n_rows = 0
        t0 = t1 = None
        bid_ok = ask_ok = last_ok = vol_ok = False
        if exists:
            try:
                if p.suffix == ".parquet":
                    df = pd.read_parquet(p)
                    n_rows = int(len(df))
                    cols = [str(c) for c in df.columns]
                    bid_ok = "bid" in df.columns
                    ask_ok = "ask" in df.columns
                    last_ok = "last" in df.columns
                    vol_ok = "volume" in df.columns
                    if "symbol" in df.columns and n_rows:
                        sample_sym = str(df["symbol"].iloc[0])
                        verified = verify_xauusd_i(symbol=sample_sym, path=path) and verified
                    ts = parse_tick_timestamps(df) if spec["category"] in {"tick", "bid_ask", "spread"} else pd.Series(_bar_opens(df))
                    ts = ts.dropna()
                    if len(ts):
                        t0 = iso_z(ts.min())
                        t1 = iso_z(ts.max())
                    del df
                else:
                    n_rows = 0
            except Exception as exc:  # noqa: BLE001 — forensic inspect
                rows.append(
                    {
                        **spec,
                        "source_name": spec["id"],
                        "source_type": "local_file",
                        "exists": True,
                        "inspect_error": str(exc),
                        "XAUUSD_i_verified": False,
                        "acquisition_status": "INVALID",
                        "access_method": "local_file",
                        "provenance": path,
                    }
                )
                continue
        status = "MISSING"
        if exists and n_rows > 0 and verified:
            status = "AVAILABLE_LOCAL"
        elif exists and n_rows > 0 and not verified:
            status = "REJECTED_SYMBOL"
        elif exists:
            status = "EMPTY"
        rows.append(
            {
                "source_name": spec["id"],
                "source_type": "local_file",
                "symbol": symbol,
                "coverage_start": t0,
                "coverage_end": t1,
                "timezone": TZ,
                "timestamp_resolution": "millisecond" if spec["category"] in {"tick", "bid_ask"} else "second",
                "bid_available": bid_ok,
                "ask_available": ask_ok,
                "last_available": last_ok,
                "volume_available": vol_ok,
                "historical_depth": None if t0 is None or t1 is None else f"{t0} → {t1}",
                "export_format": p.suffix.lstrip(".") if exists else None,
                "access_method": "local_file",
                "provenance": path,
                "XAUUSD_i_verified": verified,
                "acquisition_status": status,
                "path": path,
                "exists": exists,
                "n_rows": n_rows,
                "columns": cols,
                "category": spec["category"],
                "timeframe": spec.get("timeframe"),
                "requested_window": [iso_z(acq_start), iso_z(acq_end)],
                "mt5_used": False,
                "remote_download": False,
            }
        )
    return rows


def _load_events(root: Path) -> tuple[list[dict[str, Any]], pd.DataFrame | None]:
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    expanded = expand74(p74.get("compact_events") or [])
    by_ts = {e.get("timestamp"): e for e in expanded}
    by_class = {r.get("ts"): r.get("path_class") for r in (p90.get("compact") or [])}
    compact = p98.get("compact") or []
    df, _fp = load_frozen_ohlc(root)
    events = []
    for row in compact:
        ts = row.get("ts")
        base = by_ts.get(ts) or {}
        ts_p = _parse_ts(ts)
        hold = _f(base.get("duration_minutes")) or 0.0
        exit_ts = ts_p + timedelta(minutes=hold) if ts_p is not None else None
        anat = row.get("anatomy") or {}
        retrace = anat.get("retrace") or {}
        first_fav_bar = anat.get("first_fav_bar")
        first_adv_bar = anat.get("first_adv_bar")
        retrace_bar = retrace.get("bar") if isinstance(retrace, dict) else None
        mfe_min = _f(base.get("time_to_mfe_min"))
        entry_px = _f(base.get("entry"))
        sl = _f(base.get("SL"))
        tp = _f(base.get("TP"))

        def bar_time(j: Any) -> datetime | None:
            if df is None or j is None:
                return None
            try:
                i = int(j)
            except (TypeError, ValueError):
                return None
            if 0 <= i < len(df):
                t = pd.Timestamp(df.index[i])
                return enforce_utc(t)
            return None

        first_fav_ts = bar_time(first_fav_bar)
        first_adv_ts = bar_time(first_adv_bar)
        retrace_ts = bar_time(retrace_bar)
        mfe_ts = ts_p + timedelta(minutes=mfe_min) if ts_p is not None and mfe_min is not None else None
        same_bar = bool(anat.get("same_bar_fav_adv"))
        amb_state = any((s or {}).get("ambiguous") for s in (row.get("states") or {}).values())
        events.append(
            {
                "event_id": f"{ts}|{row.get('side')}",
                "entry_timestamp": ts_p,
                "entry_price": entry_px,
                "side": row.get("side"),
                "planned_sl": sl,
                "planned_tp": tp,
                "first_favorable_timestamp": first_fav_ts,
                "first_adverse_timestamp": first_adv_ts,
                "max_mfe_timestamp": mfe_ts,
                "retracement_timestamp": retrace_ts,
                "exit_timestamp": exit_ts,
                "exit_price": None,
                "path_class": by_class.get(ts) or row.get("path_class"),
                "r_result": row.get("orig") if row.get("orig") is not None else base.get("r_result"),
                "same_bar_fav_adv": same_bar,
                "ambiguous_394": same_bar or amb_state,
                "hold_minutes": hold,
            }
        )
    return events, df


def _event_in_range(event: dict[str, Any], tmin: pd.Timestamp, tmax: pd.Timestamp) -> bool:
    ts = event.get("entry_timestamp")
    if ts is None:
        return False
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return bool(tmin <= t <= tmax)


def _lifecycle_in_range(event: dict[str, Any], tmin: pd.Timestamp, tmax: pd.Timestamp) -> bool:
    a = event.get("entry_timestamp")
    b = event.get("exit_timestamp") or a
    if a is None:
        return False
    a = pd.Timestamp(a)
    b = pd.Timestamp(b)
    if a.tzinfo is None:
        a = a.tz_localize("UTC")
    if b.tzinfo is None:
        b = b.tz_localize("UTC")
    return bool(a >= tmin and b <= tmax)


def _ticks_cover_state(ts_ns: np.ndarray, state: datetime | None, pad_ns: int) -> bool:
    if state is None or ts_ns.size == 0:
        return False
    st = enforce_utc(state)
    if st is None:
        return False
    state_ns = int(pd.Timestamp(st).value)
    i = asof_tick_index(ts_ns, state_ns)
    if i < 0:
        return False
    return int(ts_ns[i]) >= state_ns - pad_ns


def _ingest_ticks(
    root: Path,
    sources: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    acq_start, acq_end = window_bounds()
    research = root / RESEARCH_ROOT
    (research / "ticks").mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    per_source = []
    for src in sources:
        if src.get("category") not in {"tick", "bid_ask"}:
            continue
        if not src.get("XAUUSD_i_verified"):
            continue
        if not src.get("exists"):
            continue
        if not src.get("bid_available") or not src.get("ask_available"):
            continue
        path = root / src["path"]
        df = pd.read_parquet(path)
        norm = normalize_ticks(df, source=src["path"], symbol=CANONICAL_SYMBOL)
        val = validate_tick_frame(norm)
        per_source.append(
            {
                "source_name": src["source_name"],
                "path": src["path"],
                "n_rows": int(len(norm)),
                "validation": val,
                "first": iso_z(norm["timestamp_utc"].min()) if len(norm) else None,
                "last": iso_z(norm["timestamp_utc"].max()) if len(norm) else None,
                "sha256_raw": file_sha256(path),
            }
        )
        if len(norm) and len(norm) <= 400_000:
            outp = research / "ticks" / f"{src['source_name']}.parquet"
            meta = {
                "source": src["path"],
                "symbol": CANONICAL_SYMBOL,
                "timezone": TZ,
                "acquisition_timestamp": _utc_now(),
                "normalization_version": NORMALIZATION_VERSION,
                "layer": "NORMALIZED",
                "raw_path": src["path"],
            }
            norm.to_parquet(outp, index=False)
            _write_meta(outp.with_suffix(".meta.json"), meta)
        else:
            _write_meta(
                research / "ticks" / f"{src['source_name']}_pointer.json",
                {
                    "layer": "RAW_POINTER",
                    "reason": "large tick file not duplicated; original is immutable raw",
                    "raw_path": src["path"],
                    "n_rows": int(len(norm)),
                    "symbol": CANONICAL_SYMBOL,
                    "timezone": TZ,
                    "acquisition_timestamp": _utc_now(),
                    "normalization_version": NORMALIZATION_VERSION,
                    "schema": ["timestamp_utc", "bid", "ask"],
                },
            )
        frames.append(norm[["timestamp_utc", "bid", "ask", "spread", "source"]])
        del df
    if not frames:
        return {
            "status": "MISSING",
            "total_rows": 0,
            "sources": per_source,
            "event_join": [],
            "coverage": {},
        }
    ticks = pd.concat(frames, ignore_index=True).sort_values("timestamp_utc")
    ticks = ticks.drop_duplicates(subset=["timestamp_utc", "bid", "ask"], keep="first").reset_index(drop=True)
    val = validate_tick_frame(ticks)
    ts = pd.DatetimeIndex(ticks["timestamp_utc"])
    days = trading_day_counts(ts)
    gaps = gap_statistics(ts, weekday_threshold=timedelta(minutes=5))
    ts_ns = ticks["timestamp_utc"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    bid = ticks["bid"].to_numpy(dtype=float)
    ask = ticks["ask"].to_numpy(dtype=float)
    spread = ticks["spread"].to_numpy(dtype=float)
    pad_ns = int(BAR_MINUTES * 60 * 1_000_000_000)
    tmin, tmax = ts.min(), ts.max()
    join_rows = []
    n_entry = n_exit = n_fav = n_adv = n_mfe = n_ret = n_life = 0
    n_resolved = 0
    n_amb_resolved = 0
    n_amb_remaining = 0
    chrono_counts: dict[str, int] = {c: 0 for c in CHRONOLOGY_CLASSES}
    spread_groups: dict[str, list[float]] = {"C": [], "D": [], "E": [], "F": [], "other_win": [], "other_loss": []}
    for ev in events:
        entry = ev["entry_timestamp"]
        exit_ts = ev["exit_timestamp"]
        if entry is None:
            chrono_counts["DATA_INSUFFICIENT"] += 1
            continue
        entry_ns = int(pd.Timestamp(enforce_utc(entry)).value)
        exit_ns = int(pd.Timestamp(enforce_utc(exit_ts or entry)).value)
        cov_entry = _ticks_cover_state(ts_ns, entry, pad_ns)
        cov_exit = _ticks_cover_state(ts_ns, exit_ts, pad_ns)
        cov_fav = _ticks_cover_state(ts_ns, ev["first_favorable_timestamp"], pad_ns)
        cov_adv = _ticks_cover_state(ts_ns, ev["first_adverse_timestamp"], pad_ns)
        cov_mfe = _ticks_cover_state(ts_ns, ev["max_mfe_timestamp"], pad_ns)
        cov_ret = _ticks_cover_state(ts_ns, ev["retracement_timestamp"], pad_ns)
        life = bool(cov_entry and cov_exit)
        if cov_entry:
            n_entry += 1
        if cov_exit:
            n_exit += 1
        if cov_fav or cov_adv:
            n_fav += int(cov_fav)
            n_adv += int(cov_adv)
        if cov_mfe:
            n_mfe += 1
        if cov_ret:
            n_ret += 1
        if life:
            n_life += 1
        lo = int(np.searchsorted(ts_ns, entry_ns, side="left"))
        hi = int(np.searchsorted(ts_ns, exit_ns, side="right"))
        sub_ts = ts_ns[lo:hi]
        sub_bid = bid[lo:hi]
        sub_ask = ask[lo:hi]
        chrono = classify_intrabar_order(
            str(ev.get("side")),
            float(ev["entry_price"]) if ev["entry_price"] is not None else float("nan"),
            sub_ts,
            sub_bid,
            sub_ask,
            exit_ns=exit_ns,
        )
        if len(sub_ts) == 0:
            chrono = classify_intrabar_order(str(ev.get("side")), float("nan"), np.array([]), np.array([]), np.array([]))
        chrono_counts[chrono["class"]] = chrono_counts.get(chrono["class"], 0) + 1
        if chrono["class"] in {"FAVORABLE_FIRST", "ADVERSE_FIRST"}:
            n_resolved += 1
            if ev.get("ambiguous_394"):
                n_amb_resolved += 1
        elif ev.get("ambiguous_394"):
            n_amb_remaining += 1
        i_entry = asof_tick_index(ts_ns, entry_ns)
        i_before = asof_tick_index(ts_ns, entry_ns - 1)
        i_exit = asof_tick_index(ts_ns, exit_ns)
        i_fav = asof_tick_index(ts_ns, int(pd.Timestamp(enforce_utc(ev["first_favorable_timestamp"])).value)) if ev["first_favorable_timestamp"] is not None else -1
        i_adv = asof_tick_index(ts_ns, int(pd.Timestamp(enforce_utc(ev["first_adverse_timestamp"])).value)) if ev["first_adverse_timestamp"] is not None else -1
        i_mfe = asof_tick_index(ts_ns, int(pd.Timestamp(enforce_utc(ev["max_mfe_timestamp"])).value)) if ev["max_mfe_timestamp"] is not None else -1

        def spr(i: int) -> float | None:
            if i < 0:
                return None
            v = float(spread[i])
            return v if np.isfinite(v) else None

        life_spr = spread[lo:hi] if hi > lo else np.array([])
        life_spr = life_spr[np.isfinite(life_spr)] if len(life_spr) else life_spr
        rec = {
            "event_id": ev["event_id"],
            "side": ev.get("side"),
            "path_class": ev.get("path_class"),
            "entry_timestamp": iso_z(entry),
            "exit_timestamp": iso_z(exit_ts),
            "tick_n_in_lifecycle": int(hi - lo),
            "cover_entry": cov_entry,
            "cover_exit": cov_exit,
            "cover_first_favorable": cov_fav,
            "cover_first_adverse": cov_adv,
            "cover_mfe": cov_mfe,
            "cover_retracement": cov_ret,
            "lifecycle_covered": life,
            "chronology": chrono["class"],
            "same_timestamp_ambiguous": chrono.get("same_timestamp_ambiguous"),
            "spread_at_entry": spr(i_entry) if cov_entry else None,
            "spread_before_entry": spr(i_before) if i_before >= 0 else None,
            "spread_at_first_favorable": spr(i_fav) if cov_fav else None,
            "spread_at_first_adverse": spr(i_adv) if cov_adv else None,
            "spread_at_MFE": spr(i_mfe) if cov_mfe else None,
            "spread_at_exit": spr(i_exit) if cov_exit else None,
            "max_spread_during_lifecycle": float(np.max(life_spr)) if len(life_spr) else None,
            "median_spread_during_lifecycle": float(np.median(life_spr)) if len(life_spr) else None,
        }
        join_rows.append(rec)
        klass = str(ev.get("path_class") or "")
        r = _f(ev.get("r_result"))
        bucket = klass if klass in spread_groups else ("other_win" if (r is not None and r > 0) else "other_loss")
        if rec["spread_at_entry"] is not None and rec["lifecycle_covered"]:
            spread_groups.setdefault(bucket, []).append(rec["spread_at_entry"])

    n_overlap_entry = sum(1 for e in events if _event_in_range(e, tmin, tmax))
    derived = research / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    _write_meta(derived / "event_tick_join.json", {"n": len(join_rows), "rows": join_rows})
    spread_summary = {
        k: {
            "n": len(v),
            "median": float(np.median(v)) if v else None,
            "mean": float(np.mean(v)) if v else None,
        }
        for k, v in spread_groups.items()
    }
    _write_meta(derived / "spread_event_diagnostics.json", spread_summary)
    status = quality_class(verified=True, n_rows=len(ticks), event_cov=n_life, invalid=not val["valid"])
    if status == "COMPLETE":
        tick_status = "TICK_DATA_COMPLETE"
    elif len(ticks) == 0:
        tick_status = "TICK_DATA_MISSING"
        status = "MISSING"
    else:
        tick_status = "TICK_DATA_PARTIAL"
        status = "PARTIAL"
    return {
        "status": status,
        "TICK_STATUS": tick_status,
        "SPREAD_STATUS": "SPREAD_DATA_PARTIAL" if n_life > 0 else "SPREAD_DATA_MISSING",
        "total_rows": int(len(ticks)),
        "first_timestamp": iso_z(tmin),
        "last_timestamp": iso_z(tmax),
        "full_window_covered": bool(tmin <= acq_start and tmax >= acq_end),
        "validation": val,
        "days": days,
        "gaps": gaps,
        "sources": per_source,
        "event_overlap_entry_window": n_overlap_entry,
        "TICK_EVENT_COVERAGE": n_overlap_entry,
        "TICK_COMPLETE_LIFECYCLE_EVENTS": n_life,
        "TICK_ENTRY_COVERAGE": n_entry,
        "TICK_EXIT_COVERAGE": n_exit,
        "TICK_FAV_COVERAGE": n_fav,
        "TICK_ADV_COVERAGE": n_adv,
        "TICK_MFE_COVERAGE": n_mfe,
        "TICK_RETRACE_COVERAGE": n_ret,
        "TICK_INTRABAR_RESOLUTION_COVERAGE": n_resolved,
        "chronology_counts": chrono_counts,
        "AMBIGUOUS_394_RESOLVED": n_amb_resolved,
        "AMBIGUOUS_394_REMAINING": N_AMBIGUOUS_394 - n_amb_resolved,
        "spread_summary": spread_summary,
        "bid_available": True,
        "ask_available": True,
        "median_gap_ms": gaps.get("median_gap_ms"),
        "max_gap_ms": gaps.get("max_gap_ms"),
        "window_in_range": bool(tmin <= acq_end and tmax >= acq_start),
        "event_join_n": len(join_rows),
        "join_covered": [r for r in join_rows if r["tick_n_in_lifecycle"] > 0],
    }


def _ingest_bars(
    root: Path,
    sources: list[dict[str, Any]],
    events: list[dict[str, Any]],
    category: str,
    tf_name: str,
    minutes: int,
    subdir: str,
) -> dict[str, Any]:
    acq_start, acq_end = window_bounds()
    research = root / RESEARCH_ROOT / subdir
    research.mkdir(parents=True, exist_ok=True)
    chosen = None
    for src in sources:
        if src.get("category") != category:
            continue
        if not src.get("XAUUSD_i_verified"):
            continue
        if not src.get("exists") or not src.get("n_rows"):
            continue
        chosen = src
        break
    if chosen is None:
        rejected = [s for s in sources if s.get("category") == category and s.get("exists") and not s.get("XAUUSD_i_verified")]
        _write_meta(
            research / "STATUS.json",
            {
                "layer": "MISSING",
                "symbol": CANONICAL_SYMBOL,
                "status": "MISSING",
                "rejected_unverified": [s.get("path") for s in rejected],
                "note": "Logical XAUUSD not used. EV-EQ-01 remains NOT_PROVEN.",
            },
        )
        return {
            "status": "MISSING",
            "row_count": 0,
            "event_coverage": 0,
            "lifecycle_coverage": 0,
            "causal_ready": False,
            "rejected": [s.get("path") for s in rejected],
        }
    df = pd.read_parquet(root / chosen["path"])
    norm = normalize_ohlc(df, source=chosen["path"], symbol=CANONICAL_SYMBOL)
    val = validate_ohlc_frame(norm)
    ts = pd.DatetimeIndex(norm["timestamp_utc"])
    days = trading_day_counts(ts)
    gaps = gap_statistics(ts, weekday_threshold=timedelta(minutes=minutes * 2))
    opens_ns = ts.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    dur_ns = int(minutes * 60 * 1_000_000_000)
    n_entry = n_life = n_causal = 0
    lookback_ns = int((5 + 1) * minutes * 60 * 1_000_000_000)  # REVERSAL_BARS+1, not searched from live
    for ev in events:
        entry = ev.get("entry_timestamp")
        exit_ts = ev.get("exit_timestamp") or entry
        if entry is None:
            continue
        entry_ns = int(pd.Timestamp(enforce_utc(entry)).value)
        exit_ns = int(pd.Timestamp(enforce_utc(exit_ts)).value)
        i_e = last_closed_bar_index(opens_ns, dur_ns, entry_ns)
        i_x = last_closed_bar_index(opens_ns, dur_ns, exit_ns)
        if i_e >= 0:
            n_entry += 1
            if i_e >= 0 and int(opens_ns[i_e]) >= entry_ns - lookback_ns:
                n_causal += 1
        if i_e >= 0 and i_x >= 0:
            n_life += 1
    outp = research / f"XAUUSD_i_{tf_name.lower()}.parquet"
    meta = {
        "source": chosen["path"],
        "symbol": CANONICAL_SYMBOL,
        "timezone": TZ,
        "acquisition_timestamp": _utc_now(),
        "normalization_version": NORMALIZATION_VERSION,
        "layer": "NORMALIZED",
        "closed_bar": f"open + {minutes}m <= state_timestamp",
    }
    norm.to_parquet(outp, index=False)
    _write_meta(outp.with_suffix(".meta.json"), meta)
    status = quality_class(verified=True, n_rows=len(norm), event_cov=n_life, invalid=not val["valid"])
    return {
        "status": status,
        "source": chosen["path"],
        "source_name": chosen["source_name"],
        "row_count": int(len(norm)),
        "first_timestamp": iso_z(ts.min()) if len(ts) else None,
        "last_timestamp": iso_z(ts.max()) if len(ts) else None,
        "days": days,
        "gaps": gaps,
        "validation": val,
        "event_coverage": n_entry,
        "lifecycle_coverage": n_life,
        "causal_ready_count": n_causal,
        "causal_ready": n_causal > 0 and n_life < N_EVENTS,
        "full_window": bool(len(ts) and ts.min() <= acq_start and ts.max() >= acq_end),
        "duplicate_count": val.get("duplicate_count"),
        "invalid_count": val.get("invalid_count"),
        "weekday_gap_count": gaps.get("weekday_gaps"),
        "xauusd_i_verified": True,
    }


def _cross_source(root: Path, ticks_info: dict[str, Any], m1: dict[str, Any], m15: dict[str, Any], h4: dict[str, Any]) -> dict[str, Any]:
    """Structural comparison only. Do not reconcile or alter trading logic."""
    notes = []
    m1_path = root / RESEARCH_ROOT / "m1" / "XAUUSD_i_m1.parquet"
    m15_path = root / RESEARCH_ROOT / "m15" / "XAUUSD_i_m15.parquet"
    h4_path = root / RESEARCH_ROOT / "h4" / "XAUUSD_i_h4.parquet"
    if m1_path.is_file() and m15_path.is_file():
        a = pd.read_parquet(m1_path)
        b = pd.read_parquet(m15_path)
        a_t = pd.to_datetime(a["timestamp_utc"], utc=True)
        b_t = pd.to_datetime(b["timestamp_utc"], utc=True)
        overlap_start = max(a_t.min(), b_t.min())
        overlap_end = min(a_t.max(), b_t.max())
        notes.append(
            {
                "pair": "M1_vs_M15",
                "overlap_start": iso_z(overlap_start),
                "overlap_end": iso_z(overlap_end),
                "discrepancy": "different timeframes; not expected to be row-identical; both preserved",
                "reconciled": False,
            }
        )
    if m15_path.is_file() and h4_path.is_file():
        notes.append(
            {
                "pair": "M15_vs_H4",
                "m15_rows": m15.get("row_count"),
                "h4_rows": h4.get("row_count"),
                "discrepancy": "H4 coverage is a short snapshot; M15 is longer; both preserved",
                "reconciled": False,
            }
        )
    tick_m1 = {
        "pair": "tick_derived_M1_vs_canonical_M1",
        "attempted": False,
        "note": "tick window and M1 window barely overlap; no silent resample used as canonical M1",
        "reconciled": False,
    }
    if ticks_info.get("total_rows") and m1.get("row_count"):
        tick_m1["attempted"] = True
        tick_m1["tick_first"] = ticks_info.get("first_timestamp")
        tick_m1["tick_last"] = ticks_info.get("last_timestamp")
        tick_m1["m1_first"] = m1.get("first_timestamp")
        tick_m1["m1_last"] = m1.get("last_timestamp")
    notes.append(tick_m1)
    notes.append(
        {
            "pair": "H1_canonical_vs_logical_XAUUSD_1h",
            "canonical": "MISSING",
            "logical_rejected": True,
            "reconciled": False,
            "ev_eq_01": "NOT_PROVEN",
        }
    )
    return {"comparisons": notes, "silent_reconcile": False}


def _outlier_status(events: list[dict[str, Any]], ticks_info: dict[str, Any]) -> dict[str, Any]:
    f_ev = None
    for e in events:
        r = _f(e.get("r_result"))
        if e.get("path_class") == "F" or (r is not None and abs(r - 31.84) < 0.05):
            f_ev = e
            break
    if f_ev is None:
        return {"found": False, "OUTLIER_31_84R_TICK_COVERAGE": False, "OUTLIER_31_84R_CHRONOLOGY_STATUS": "DATA_INSUFFICIENT"}
    covered = any(r.get("event_id") == f_ev["event_id"] and r.get("lifecycle_covered") for r in ticks_info.get("join_covered") or [])
    chrono = "DATA_INSUFFICIENT"
    for r in ticks_info.get("join_covered") or []:
        if r.get("event_id") == f_ev["event_id"]:
            chrono = r.get("chronology")
    all_join = _safe_load_json(Path())  # placeholder unused
    return {
        "found": True,
        "event_id": f_ev["event_id"],
        "entry_timestamp": iso_z(f_ev.get("entry_timestamp")),
        "exit_timestamp": iso_z(f_ev.get("exit_timestamp")),
        "path_class": f_ev.get("path_class"),
        "r_result": f_ev.get("r_result"),
        "OUTLIER_31_84R_TICK_COVERAGE": bool(covered),
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": chrono if covered else "DATA_INSUFFICIENT",
        "do_not_cap_path": True,
    }


def _path_cd_ef(events: list[dict[str, Any]], ticks_info: dict[str, Any]) -> dict[str, Any]:
    covered_ids = {r["event_id"] for r in ticks_info.get("join_covered") or [] if r.get("lifecycle_covered")}
    by = {"C": 0, "D": 0, "E": 0, "F": 0}
    cov = {"C": 0, "D": 0, "E": 0, "F": 0}
    for e in events:
        k = str(e.get("path_class") or "")
        if k in by:
            by[k] += 1
            if e["event_id"] in covered_ids:
                cov[k] += 1
    distinguishable = all(cov[k] >= 8 for k in ("C", "D", "E")) and cov["F"] >= 1
    return {
        "population": by,
        "tick_lifecycle_covered": cov,
        "C_VS_D_VS_E_VS_F_STATUS": "DISTINGUISHABLE_AT_EVENT_LEVEL" if distinguishable else "DATA_INSUFFICIENT",
        "note": "Descriptive coverage only. No causality claimed. No discriminator selected.",
    }


def _news_status(root: Path) -> dict[str, Any]:
    gen = root / NEWS_GENERATOR
    research = root / RESEARCH_ROOT / "news"
    research.mkdir(parents=True, exist_ok=True)
    payload = {
        "NEWS_STATUS": "NEWS_DATA_MISSING",
        "NEWS_DATA_STATUS": "MISSING",
        "historical_source": None,
        "generator_present": gen.is_file(),
        "generator_used": False,
        "reason": "No verified historical scheduled-event file. In-repo news generator is not a historical calendar.",
        "causal_rule": "scheduled_time < entry_timestamp only; actuals are not causal predictors",
        "minutes_before": NEWS_MINUTES_BEFORE,
    }
    _write_meta(research / "STATUS.json", payload)
    return payload


def _frozen_integrity(root: Path) -> dict[str, Any]:
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    jsonl = root / PHASE40_SETUPS_JSONL
    sha = file_sha256(jsonl)
    ts = p40.get("timestamp_utc")
    fp = p40.get("tape_fingerprint") or p40.get("fingerprint")
    ok = ts == PHASE40_TS and fp == FROZEN and sha == EXPECTED_JSONL_SHA256
    return {
        "ok": ok,
        "FROZEN_PHASE40_TIMESTAMP": ts,
        "FROZEN_PHASE40_FINGERPRINT": fp,
        "FROZEN_PHASE40_SHA256": sha,
        "expected_timestamp": PHASE40_TS,
        "expected_fingerprint": FROZEN,
        "expected_sha256": EXPECTED_JSONL_SHA256,
        "jsonl_byte_identical": sha == EXPECTED_JSONL_SHA256,
        "repaired": False,
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phase 115 (`docs/PHASE115_NON_OHLC_DATA_ACQUISITION.md`) is research-only "
        "local XAUUSD_i ingest. It does not connect to MT5, read .env, synthesize ticks, "
        "modify production, or implement an exit spec. Phase 116 was not started."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phase 114 (`docs/PHASE114_NON_OHLC_ACQUISITION_CONTRACT.md`)"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase115_non_ohlc_data_acquisition.py` — **RESEARCH_ONLY** "
        "local non-OHLC ingest; no MT5; no exit spec.\n"
    )
    needle = "`tradingbot/backtest/phase114_non_ohlc_acquisition_contract.py`"
    if "phase115_non_ohlc_data_acquisition.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 115 started | **NO** |", "| Phase 115 started | **YES** |")
    block = f"""

## Non-OHLC data acquisition (Phase 115)

| Claim | Status |
|---|---|
| PHASE115_STATUS | **{payload.get("PHASE115_STATUS")}** |
| ACQUISITION_STATUS | **{payload.get("ACQUISITION_STATUS")}** |
| INGESTION_STATUS | **{payload.get("INGESTION_STATUS")}** |
| DATA_QUALITY_STATUS | **{payload.get("DATA_QUALITY_STATUS")}** |
| PHASE116_READY | **{payload.get("PHASE116_READY")}** |
| TICK_STATUS | **{payload.get("TICK_STATUS")}** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| EV-EQ-01 | **NOT_PROVEN** |
| Intervention implemented | **NO** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 116 started | **NO** |
"""
    marker = "## Non-OHLC data acquisition (Phase 115)"
    if marker in ktext:
        start = ktext.find(marker)
        ku.write_text(ktext[:start].rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")


def append_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = root / LEDGER_MD
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    extra = [
        "",
        "## Phase 115",
        "",
        "| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| H115-01 | {today} | 115 | frozen Phase38/40 | 419 | event tape 419 resolved | {payload.get('PHASE116_READY')} | reported | NO | ingest; Phase 116 not started |",
        "",
        f"**PHASE115_STATUS:** `{payload.get('PHASE115_STATUS')}`",
        f"**ACQUISITION_STATUS:** `{payload.get('ACQUISITION_STATUS')}`",
        f"**TICK_COMPLETE_LIFECYCLE_EVENTS:** `{payload.get('TICK_COMPLETE_LIFECYCLE_EVENTS')}`",
        f"**PHASE116_READY:** `{payload.get('PHASE116_READY')}`",
        "",
    ]
    marker = "## Phase 115"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    t = payload.get("ticks") or {}
    lines = [
        "# Phase 115 — Non-OHLC Data Acquisition & Ingestion",
        "",
        "FROZEN-DATA-EVIDENCE (local files) and CODE-EVIDENCE (joins). Not exit-design research.",
        "",
        f"PHASE115_STATUS = {payload.get('PHASE115_STATUS')}",
        f"ACQUISITION_STATUS = {payload.get('ACQUISITION_STATUS')}",
        f"INGESTION_STATUS = {payload.get('INGESTION_STATUS')}",
        f"DATA_QUALITY_STATUS = {payload.get('DATA_QUALITY_STATUS')}",
        f"PHASE116_READY = {payload.get('PHASE116_READY')}",
        "",
        f"TICK_STATUS = {payload.get('TICK_STATUS')}",
        f"SPREAD_STATUS = {payload.get('SPREAD_STATUS')}",
        f"M1_STATUS = {payload.get('M1_STATUS')}",
        f"M15_STATUS = {payload.get('M15_STATUS')}",
        f"H1_STATUS = {payload.get('H1_STATUS')}",
        f"H4_STATUS = {payload.get('H4_STATUS')}",
        f"NEWS_STATUS = {payload.get('NEWS_STATUS')}",
        "",
        f"TICK_EVENT_COVERAGE = {payload.get('TICK_EVENT_COVERAGE')}",
        f"TICK_COMPLETE_LIFECYCLE_EVENTS = {payload.get('TICK_COMPLETE_LIFECYCLE_EVENTS')}",
        f"TICK_ENTRY_COVERAGE = {payload.get('TICK_ENTRY_COVERAGE')}",
        f"TICK_EXIT_COVERAGE = {payload.get('TICK_EXIT_COVERAGE')}",
        f"TICK_INTRABAR_RESOLUTION_COVERAGE = {payload.get('TICK_INTRABAR_RESOLUTION_COVERAGE')}",
        "",
        f"AMBIGUOUS_394_RESOLVED = {payload.get('AMBIGUOUS_394_RESOLVED')}",
        f"AMBIGUOUS_394_REMAINING = {payload.get('AMBIGUOUS_394_REMAINING')}",
        "",
        f"OUTLIER_31_84R_TICK_COVERAGE = {payload.get('OUTLIER_31_84R_TICK_COVERAGE')}",
        f"OUTLIER_31_84R_CHRONOLOGY_STATUS = {payload.get('OUTLIER_31_84R_CHRONOLOGY_STATUS')}",
        "",
        f"C_VS_D_VS_E_VS_F_STATUS = {payload.get('C_VS_D_VS_E_VS_F_STATUS')}",
        f"SPREAD_INFORMATION_STATUS = {payload.get('SPREAD_INFORMATION_STATUS')}",
        f"M1_INCREMENTAL_INFORMATION_STATUS = {payload.get('M1_INCREMENTAL_INFORMATION_STATUS')}",
        f"H1_INFORMATION_STATUS = {payload.get('H1_INFORMATION_STATUS')}",
        f"NEWS_INFORMATION_STATUS = {payload.get('NEWS_INFORMATION_STATUS')}",
        "",
        f"REMAINING_UNKNOWN = {payload.get('REMAINING_UNKNOWN')}",
        "",
        "## Safety",
        "",
        "No MT5, no .env, no orders, no production changes, no exit-rule tests.",
        "Ticks were not synthesized. Missing bid/ask was not replaced with OHLC.",
        "Logical XAUUSD was not substituted for XAUUSD_i. EV-EQ-01 remains NOT_PROVEN.",
        "",
        "## Sources",
        "",
        json.dumps(payload.get("sources_summary"), indent=2, default=str),
        "",
        "## Tick window",
        "",
        f"- rows: `{t.get('total_rows')}`",
        f"- first: `{t.get('first_timestamp')}`",
        f"- last: `{t.get('last_timestamp')}`",
        f"- calendar days: `{((t.get('days') or {}).get('calendar_days'))}`",
        f"- active trading days: `{((t.get('days') or {}).get('active_trading_days'))}`",
        "",
        "Full acquisition window was not covered by local ticks.",
        "",
        "## Execution semantics (research reconstruction only)",
        "",
        "- long favorable: ask > entry; long adverse: bid < entry",
        "- short favorable: bid < entry; short adverse: ask > entry",
        "- same-timestamp fav+adv → SIMULTANEOUS_UNRESOLVED",
        "- production execution unchanged",
        "",
        "Phase 116 was not started.",
        "",
    ]
    (root / PHASE115_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_phase115_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    frozen = _frozen_integrity(root)
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    n_amb = int(p98.get("n_ambiguous") or N_AMBIGUOUS_394)
    events, _df = _load_events(root)
    sources = _discover_sources(root)
    research = root / RESEARCH_ROOT
    (research / "raw").mkdir(parents=True, exist_ok=True)
    _write_meta(
        research / "raw" / "provenance.json",
        {
            "layer": "RAW",
            "immutable_originals": True,
            "copied": False,
            "timezone": TZ,
            "symbol": CANONICAL_SYMBOL,
            "acquisition_timestamp": _utc_now(),
            "normalization_version": NORMALIZATION_VERSION,
            "sources": sources,
            "mt5_used": False,
            "remote_download": False,
        },
    )
    ticks = _ingest_ticks(root, sources, events)
    m1 = _ingest_bars(root, sources, events, "m1", "M1", M1_MINUTES, "m1")
    m15 = _ingest_bars(root, sources, events, "m15", "M15", M15_MINUTES, "m15")
    h1 = _ingest_bars(root, sources, events, "h1", "H1", H1_MINUTES, "h1")
    h4 = _ingest_bars(root, sources, events, "h4", "H4", H4_MINUTES, "h4")
    news = _news_status(root)
    cross = _cross_source(root, ticks, m1, m15, h4)
    outlier = _outlier_status(events, ticks)
    paths = _path_cd_ef(events, ticks)
    acq_start, acq_end = window_bounds()
    req_s, req_e = iso_z(acq_start), iso_z(acq_end)
    matrix = [
        coverage_row(
            "union_local_xauusd_i_ticks",
            "tick",
            CANONICAL_SYMBOL,
            req_s or "",
            req_e or "",
            ticks.get("first_timestamp"),
            ticks.get("last_timestamp"),
            int(ticks.get("total_rows") or 0),
            int(ticks.get("TICK_EVENT_COVERAGE") or 0),
            int(ticks.get("TICK_COMPLETE_LIFECYCLE_EVENTS") or 0),
            int((ticks.get("gaps") or {}).get("weekday_gaps") or 0),
            int((ticks.get("validation") or {}).get("duplicate_timestamps") or 0),
            int((ticks.get("validation") or {}).get("invalid_rows") or 0),
            bool((ticks.get("TICK_COMPLETE_LIFECYCLE_EVENTS") or 0) > 0),
            True,
            ticks.get("status") or "MISSING",
            extra={
                "bid_available": True,
                "ask_available": True,
                "median_gap_ms": ticks.get("median_gap_ms"),
                "max_gap_ms": ticks.get("max_gap_ms"),
            },
        ),
        coverage_row(
            m1.get("source") or "m1",
            "M1",
            CANONICAL_SYMBOL,
            req_s or "",
            req_e or "",
            m1.get("first_timestamp"),
            m1.get("last_timestamp"),
            int(m1.get("row_count") or 0),
            int(m1.get("event_coverage") or 0),
            int(m1.get("lifecycle_coverage") or 0),
            int(m1.get("weekday_gap_count") or 0),
            int(m1.get("duplicate_count") or 0),
            int(m1.get("invalid_count") or 0),
            bool(m1.get("causal_ready_count")),
            bool(m1.get("xauusd_i_verified")),
            m1.get("status") or "MISSING",
        ),
        coverage_row(
            m15.get("source") or "m15",
            "M15",
            CANONICAL_SYMBOL,
            req_s or "",
            req_e or "",
            m15.get("first_timestamp"),
            m15.get("last_timestamp"),
            int(m15.get("row_count") or 0),
            int(m15.get("event_coverage") or 0),
            int(m15.get("lifecycle_coverage") or 0),
            int(m15.get("weekday_gap_count") or 0),
            int(m15.get("duplicate_count") or 0),
            int(m15.get("invalid_count") or 0),
            True,
            bool(m15.get("xauusd_i_verified")),
            m15.get("status") or "MISSING",
        ),
        coverage_row(
            "canonical_h1",
            "H1",
            CANONICAL_SYMBOL,
            req_s or "",
            req_e or "",
            h1.get("first_timestamp"),
            h1.get("last_timestamp"),
            int(h1.get("row_count") or 0),
            int(h1.get("event_coverage") or 0),
            int(h1.get("lifecycle_coverage") or 0),
            int(h1.get("weekday_gap_count") or 0),
            int(h1.get("duplicate_count") or 0),
            int(h1.get("invalid_count") or 0),
            False,
            bool(h1.get("xauusd_i_verified")),
            h1.get("status") or "MISSING",
        ),
        coverage_row(
            h4.get("source") or "h4",
            "H4",
            CANONICAL_SYMBOL,
            req_s or "",
            req_e or "",
            h4.get("first_timestamp"),
            h4.get("last_timestamp"),
            int(h4.get("row_count") or 0),
            int(h4.get("event_coverage") or 0),
            int(h4.get("lifecycle_coverage") or 0),
            int(h4.get("weekday_gap_count") or 0),
            int(h4.get("duplicate_count") or 0),
            int(h4.get("invalid_count") or 0),
            bool(h4.get("causal_ready_count")),
            bool(h4.get("xauusd_i_verified")),
            h4.get("status") or "MISSING",
        ),
        coverage_row(
            "historical_news",
            "news",
            "calendar",
            req_s or "",
            req_e or "",
            None,
            None,
            0,
            0,
            0,
            0,
            0,
            0,
            False,
            False,
            "MISSING",
        ),
    ]
    (research / "derived").mkdir(parents=True, exist_ok=True)
    _write_meta(research / "derived" / "coverage_matrix.json", {"rows": matrix})
    n_life = int(ticks.get("TICK_COMPLETE_LIFECYCLE_EVENTS") or 0)
    n_resolved = int(ticks.get("TICK_INTRABAR_RESOLUTION_COVERAGE") or 0)
    ready = bool(n_life >= 8 and n_resolved >= 8 and outlier.get("OUTLIER_31_84R_TICK_COVERAGE"))
    remaining = (
        "Full-horizon XAUUSD_i tick bid/ask covering 2023-02-26T15:40:00Z–2026-09-07T20:10:00Z; "
        "canonical XAUUSD_i H1; M15 gap before 2024-07-25; H4 full horizon; "
        "historical scheduled news/calendar. Local ticks cover only a late-2026 sidecar window."
    )
    m1_inc = (
        "M1_ADDS_NO_INTRABAR_ORDER"
        if int(m1.get("event_coverage") or 0) > 0
        else "M1_DATA_PARTIAL_NO_INCREMENTAL_INTRABAR"
    )
    if int(m1.get("event_coverage") or 0) == 0:
        m1_inc = "M1_DATA_INSUFFICIENT"
    status = "PASS" if frozen.get("ok") else "FAIL"
    if not frozen.get("ok"):
        ready = False
    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": status,
        "PHASE115_STATUS": status,
        "ACQUISITION_STATUS": "LOCAL_SIDECARS_ONLY",
        "INGESTION_STATUS": "COMPLETE_FOR_AVAILABLE_SOURCES",
        "DATA_QUALITY_STATUS": "PARTIAL",
        "PHASE116_READY": ready,
        "TICK_STATUS": ticks.get("TICK_STATUS") or "TICK_DATA_MISSING",
        "SPREAD_STATUS": ticks.get("SPREAD_STATUS") or "SPREAD_DATA_MISSING",
        "M1_STATUS": f"M1_DATA_{m1.get('status') or 'MISSING'}",
        "M15_STATUS": f"M15_DATA_{m15.get('status') or 'MISSING'}",
        "H1_STATUS": "H1_DATA_MISSING",
        "H4_STATUS": f"H4_DATA_{h4.get('status') or 'MISSING'}",
        "NEWS_STATUS": news.get("NEWS_STATUS"),
        "TICK_EVENT_COVERAGE": ticks.get("TICK_EVENT_COVERAGE") or 0,
        "TICK_COMPLETE_LIFECYCLE_EVENTS": n_life,
        "TICK_ENTRY_COVERAGE": ticks.get("TICK_ENTRY_COVERAGE") or 0,
        "TICK_EXIT_COVERAGE": ticks.get("TICK_EXIT_COVERAGE") or 0,
        "TICK_INTRABAR_RESOLUTION_COVERAGE": n_resolved,
        "AMBIGUOUS_394_RESOLVED": ticks.get("AMBIGUOUS_394_RESOLVED") or 0,
        "AMBIGUOUS_394_REMAINING": ticks.get("AMBIGUOUS_394_REMAINING") if ticks.get("AMBIGUOUS_394_REMAINING") is not None else n_amb,
        "n_ambiguous_phase98": n_amb,
        "OUTLIER_31_84R_TICK_COVERAGE": outlier.get("OUTLIER_31_84R_TICK_COVERAGE"),
        "OUTLIER_31_84R_CHRONOLOGY_STATUS": outlier.get("OUTLIER_31_84R_CHRONOLOGY_STATUS"),
        "C_VS_D_VS_E_VS_F_STATUS": paths.get("C_VS_D_VS_E_VS_F_STATUS"),
        "SPREAD_INFORMATION_STATUS": (
            "DESCRIPTIVE_ONLY_N_LT_MIN_BIN" if n_life > 0 else "SPREAD_DATA_MISSING"
        ),
        "M1_INCREMENTAL_INFORMATION_STATUS": m1_inc,
        "H1_INFORMATION_STATUS": "H1_CANONICAL_MISSING",
        "NEWS_INFORMATION_STATUS": "NEWS_DATA_MISSING",
        "REMAINING_UNKNOWN": remaining,
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "data_acquired": True,
        "DATA_ACQUIRED": True,
        "DATA_ACQUIRED_SCOPE": "LOCAL_SIDECARS_ONLY",
        "remote_download": False,
        "ticks_synthesized": False,
        "ohlc_used_as_ticks": False,
        "intervention_implemented": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "n_events": len(events),
        "n_raw_signals_not_independent": 2847,
        "outlier_kept": True,
        "sources": sources,
        "sources_summary": [
            {
                "source_name": s.get("source_name"),
                "path": s.get("path"),
                "XAUUSD_i_verified": s.get("XAUUSD_i_verified"),
                "acquisition_status": s.get("acquisition_status"),
                "n_rows": s.get("n_rows"),
                "coverage_start": s.get("coverage_start"),
                "coverage_end": s.get("coverage_end"),
            }
            for s in sources
        ],
        "ticks": {k: v for k, v in ticks.items() if k != "join_covered"},
        "m1": m1,
        "m15": m15,
        "h1": h1,
        "h4": h4,
        "news": news,
        "cross_source": cross,
        "outlier": outlier,
        "path_classes": paths,
        "coverage_matrix": matrix,
        "research_readiness": {
            "q1_tick_sufficient_for_meaningful_n": False,
            "q2_coverage": {
                "entry": ticks.get("TICK_ENTRY_COVERAGE") or 0,
                "fav_adv": {
                    "fav": ticks.get("TICK_FAV_COVERAGE") or 0,
                    "adv": ticks.get("TICK_ADV_COVERAGE") or 0,
                },
                "mfe": ticks.get("TICK_MFE_COVERAGE") or 0,
                "retracement": ticks.get("TICK_RETRACE_COVERAGE") or 0,
                "exit": ticks.get("TICK_EXIT_COVERAGE") or 0,
            },
            "q3_complete_lifecycle": n_life,
            "q4_ambiguous_394_ordered": ticks.get("AMBIGUOUS_394_RESOLVED") or 0,
            "q5_outlier_covered": outlier.get("OUTLIER_31_84R_TICK_COVERAGE"),
            "q6_outlier_chronology_resolved": outlier.get("OUTLIER_31_84R_CHRONOLOGY_STATUS")
            in {"FAVORABLE_FIRST", "ADVERSE_FIRST"},
            "q7_cd_vs_ef_distinguishable": paths.get("C_VS_D_VS_E_VS_F_STATUS") == "DISTINGUISHABLE_AT_EVENT_LEVEL",
            "q8_spread_explanatory": False,
            "q9_m1_beyond_ticks": False,
            "q10_h1_causally_joinable": False,
            "q11_news_usable": False,
            "q12_remaining_unknown": remaining,
        },
        "chronology_semantics": {
            "long_favorable": "ask > entry",
            "long_adverse": "bid < entry",
            "short_favorable": "bid < entry",
            "short_adverse": "ask > entry",
            "same_bar_sl_not_assumed_favorable_first": True,
            "production_execution_unchanged": True,
        },
        "TESTS_PHASE115": None,
        "REGRESSION_40_43_57_63_68_115": None,
        "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
        "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"),
        "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
        "frozen_integrity": frozen,
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
        "PARAMETER_SEARCH_USED": False,
        "PRIMARY_EXIT_MECHANISM": "PROFIT_GIVEBACK",
        "SECONDARY_EXIT_MECHANISM": "EXIT_GEOMETRY",
        "DISCRIMINATOR_STATUS": "UNSUPPORTED",
        "EXIT_DESIGN_SPEC_STATUS": "INSUFFICIENT_EVIDENCE",
        "FINAL_GATE": "GO_RESEARCH" if frozen.get("ok") else "FAIL",
        "FINAL_RESEARCH_GATE": "GO_RESEARCH" if frozen.get("ok") else "FAIL",
        "NEXT_RESEARCH_TARGET": "PHASE116_NOT_STARTED",
        "evidence_kind": "FROZEN-DATA-EVIDENCE",
        "hypotheses": [
            {
                "id": "H115-01",
                "claim": "Local XAUUSD_i non-OHLC files can be ingested without MT5 and measured against the 419-event tape.",
                "result": "SUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["local_ingest", "tick_asof", "coverage_matrix"],
        "oos_used_for_selection": False,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "OPTIMIZATION": "NOT_PERFORMED",
            "MT5": "NOT_USED",
            "DATA_ACQUIRED": True,
            "DATA_ACQUIRED_SCOPE": "LOCAL_SIDECARS_ONLY",
            "production_changes": "NONE",
            "spec_implemented": False,
            "ticks_synthesized": False,
        },
        "git_head": _git_head(root),
        "artifacts": {
            "json": PHASE115_JSON,
            "md": PHASE115_MD,
            "ledger": LEDGER_MD,
            "research_root": RESEARCH_ROOT,
            "coverage_matrix": f"{RESEARCH_ROOT}/derived/coverage_matrix.json",
        },
    }
    if not frozen.get("ok"):
        payload["PHASE115_STATUS"] = "FAIL"
        payload["blocker"] = "Frozen Phase 40 jsonl/fingerprint/timestamp mismatch. File was not repaired."
    (root / PHASE115_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE115_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    _write_md(root, payload)
    _patch_truth(root, payload)
    append_ledger(root, payload)
    return payload


def apply_test_results(root: Path, phase115: dict[str, Any], regression: dict[str, Any]) -> None:
    path = root / PHASE115_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["TESTS_PHASE115"] = phase115
    payload["REGRESSION_40_43_57_63_68_115"] = regression
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = root / PHASE115_MD
    text = md.read_text(encoding="utf-8")
    block = (
        f"\nTESTS_PHASE115 = {phase115}\n"
        f"REGRESSION_40_43_57_63_68_115 = {regression}\n"
    )
    if "TESTS_PHASE115 =" not in text.split("REMAINING_UNKNOWN")[-1]:
        md.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    else:
        md.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
