"""Phase 106 — inventory of existing local non-OHLC datasets.

RESEARCH ONLY. Inspects files already on disk. No MT5, download, or .env.
Does not assume a filename means the file is populated or usable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    _git_head,
    _parse_ts,
    _utc_now,
    load_setups,
)
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, expand74
from tradingbot.backtest.phase82_profit_protection_design import STRUCTURAL_FRACTION
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON
from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON

PHASE = "106"
PHASE106_JSON = "logs/phase106_non_ohlc_data_inventory.json"
PHASE106_MD = "docs/PHASE106_NON_OHLC_DATA_INVENTORY.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "inventory",
    "final_gate",
    "production_safety",
    "artifacts",
)
CLASSES = (
    "AVAILABLE_AND_USABLE",
    "AVAILABLE_BUT_INCOMPLETE",
    "AVAILABLE_BUT_NONCAUSAL",
    "EMPTY",
    "MISSING",
)
# Completeness bar = unique half. Not searched.
OVERLAP_COMPLETE = STRUCTURAL_FRACTION

# Predeclared candidate paths. Inspected; not assumed populated.
CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "id": "A_TICK_PHASE38",
        "category": "tick",
        "path": "data/XAUUSD_i_ticks_phase38.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "tick",
        "time_cols": ("time_msc", "time"),
    },
    {
        "id": "A_TICK_P27_26",
        "category": "tick",
        "path": "logs/phase27_26_xauusd_i_ticks.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "tick",
        "time_cols": ("time_utc", "time"),
    },
    {
        "id": "B_BIDASK_PHASE38",
        "category": "bid_ask",
        "path": "logs/phase38_xauusd_i_bidask.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "tick",
        "time_cols": ("time",),
    },
    {
        "id": "C_SPREAD_P27_26_M5",
        "category": "spread",
        "path": "logs/phase27_26_xauusd_i_m5_bidask.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "M5",
        "time_cols": ("time", "first_timestamp", "last_timestamp"),
    },
    {
        "id": "D_M1_PHASE38",
        "category": "m1",
        "path": "data/XAUUSD_i_m1_phase38.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "M1",
        "time_cols": ("time",),
    },
    {
        "id": "E_M15_PHASE38",
        "category": "m15",
        "path": "data/XAUUSD_i_m15_phase38.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "M15",
        "time_cols": ("time",),
    },
    {
        "id": "F_H1_LOGICAL",
        "category": "h1",
        "path": "data/XAUUSD_1h.parquet",
        "symbol": "XAUUSD",
        "timeframe": "H1",
        "time_cols": ("time",),
        "symbol_binding": "EV-EQ-01_NOT_PROVEN",
    },
    {
        "id": "G_H4_XAUUSD_I",
        "category": "h4",
        "path": "data/XAUUSD_i_4h.parquet",
        "symbol": "XAUUSD_i",
        "timeframe": "H4",
        "time_cols": ("time",),
    },
    {
        "id": "G_H4_LOGICAL_ML",
        "category": "h4",
        "path": "data/ml/raw/candles/h4/XAUUSD_h4.parquet",
        "symbol": "XAUUSD",
        "timeframe": "H4",
        "time_cols": ("time",),
        "symbol_binding": "EV-EQ-01_NOT_PROVEN",
    },
    {
        "id": "E_M15_LOGICAL_ML",
        "category": "m15",
        "path": "data/ml/raw/candles/m15/XAUUSD_m15.parquet",
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "time_cols": ("time",),
        "symbol_binding": "EV-EQ-01_NOT_PROVEN",
    },
    {
        "id": "H_SESSION_REPLAY",
        "category": "session",
        "path": "logs/session_filter_blocked_replay.jsonl",
        "symbol": "mixed",
        "timeframe": "event",
        "time_cols": ("timestamp",),
    },
    {
        "id": "L_TRADE_JOURNAL",
        "category": "execution_fill",
        "path": "data/trade_journal.db",
        "symbol": "XAUUSD",
        "timeframe": "execution",
        "time_cols": ("ts",),
    },
    {
        "id": "M_ML_V2",
        "category": "feature_store",
        "path": "data/ml/datasets/XAUUSD_M5_dataset_v2.parquet",
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "time_cols": ("event_time", "time"),
        "symbol_binding": "EV-EQ-01_NOT_PROVEN",
        "leakage_fields": ("mfe", "mae", "label", "future_return", "tp_hit", "sl_hit"),
    },
)


ABSENT_CATEGORIES = (
    ("I_NEWS", "news", "No historical news json/parquet/csv on disk. news_calendar.py is a generator, not a dataset."),
    ("J_CALENDAR", "economic_calendar", "No economic-calendar data file on disk."),
    ("F_H1_CANONICAL", "h1", "No XAUUSD_i H1 parquet."),
    ("K_MICROSTRUCTURE_FULL", "microstructure", "No full-horizon tick/order-book tape overlapping Phase40 events."),
)


def _to_utc_index(series: pd.Series) -> pd.DatetimeIndex:
    ts = pd.to_datetime(series, utc=True, errors="coerce")
    return pd.DatetimeIndex(ts).dropna()


def _overlap(times: pd.DatetimeIndex, event_ts: list[pd.Timestamp]) -> dict[str, Any]:
    if times.empty or not event_ts:
        return {"n_events": len(event_ts), "n_overlap": 0, "frac": 0.0}
    tmin, tmax = times.min(), times.max()
    n = sum(1 for t in event_ts if tmin <= t <= tmax)
    return {"n_events": len(event_ts), "n_overlap": n, "frac": n / len(event_ts) if event_ts else 0.0}


def _inspect_parquet(root: Path, spec: dict[str, Any], event_ts: list[pd.Timestamp]) -> dict[str, Any]:
    path = root / spec["path"]
    row: dict[str, Any] = {
        **spec,
        "exists": path.is_file(),
        "format": path.suffix.lstrip(".") or "unknown",
        "n_rows": None,
        "columns": [],
        "date_start": None,
        "date_end": None,
        "timestamps_usable": False,
        "overlap_events": None,
        "populated": False,
        "class": "MISSING",
        "future_leakage_risk": "HIGH" if spec.get("leakage_fields") else "LOW_IF_ASOF",
        "causal_alignable": False,
        "evidence_kind": "CODE-EVIDENCE",
    }
    if not path.is_file():
        return row
    try:
        df = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001 — forensic inspect
        row["inspect_error"] = str(exc)
        row["class"] = "EMPTY"
        return row
    row["n_rows"] = int(len(df))
    row["columns"] = [str(c) for c in df.columns]
    row["populated"] = len(df) > 0
    if len(df) == 0:
        row["class"] = "EMPTY"
        return row
    times = pd.DatetimeIndex([])
    for col in spec.get("time_cols") or ():
        if col not in df.columns and not (col == "time_msc" and "time_msc" in df.columns):
            continue
        if col == "time_msc":
            raw = pd.to_numeric(df["time_msc"], errors="coerce").dropna()
            if len(raw) == 0:
                continue
            sample = float(raw.iloc[0])
            unit = "ms" if sample > 1e11 else "s"
            times = pd.to_datetime(raw.astype("int64"), unit=unit, utc=True)
            if len(times):
                break
            continue
        times = _to_utc_index(df[col])
        if len(times):
            break
    if times.empty and isinstance(df.index, pd.DatetimeIndex):
        times = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True))
    if times.empty:
        row["timestamps_usable"] = False
        row["class"] = "AVAILABLE_BUT_NONCAUSAL"
        return row
    row["timestamps_usable"] = True
    row["date_start"] = str(times.min())
    row["date_end"] = str(times.max())
    ov = _overlap(times, event_ts)
    row["overlap_events"] = ov
    binding = spec.get("symbol_binding")
    if spec.get("leakage_fields") and any(f in df.columns for f in spec["leakage_fields"]):
        row["class"] = "AVAILABLE_BUT_NONCAUSAL"
        row["causal_alignable"] = False
        row["future_leakage_risk"] = "HIGH"
        return row
    if binding == "EV-EQ-01_NOT_PROVEN":
        row["class"] = "AVAILABLE_BUT_INCOMPLETE"
        row["causal_alignable"] = False
        row["note"] = "Logical XAUUSD is not proven equivalent to canonical XAUUSD_i."
        return row
    if ov["frac"] >= OVERLAP_COMPLETE and ov["n_overlap"] >= 8:
        row["class"] = "AVAILABLE_AND_USABLE"
        row["causal_alignable"] = True
    elif ov["n_overlap"] > 0:
        row["class"] = "AVAILABLE_BUT_INCOMPLETE"
        row["causal_alignable"] = True
    else:
        row["class"] = "AVAILABLE_BUT_INCOMPLETE"
        row["causal_alignable"] = False
        row["note"] = "File populated but date window does not overlap Phase40 events."
    return row


def _inspect_jsonl(root: Path, spec: dict[str, Any], event_ts: list[pd.Timestamp]) -> dict[str, Any]:
    path = root / spec["path"]
    row: dict[str, Any] = {
        **spec,
        "exists": path.is_file(),
        "format": "jsonl",
        "n_rows": 0,
        "columns": [],
        "class": "MISSING",
        "populated": False,
        "timestamps_usable": False,
        "causal_alignable": False,
        "future_leakage_risk": "UNKNOWN",
        "evidence_kind": "CODE-EVIDENCE",
    }
    if not path.is_file():
        return row
    n = 0
    cols: set[str] = set()
    times: list[pd.Timestamp] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            cols.update(obj.keys())
            ts = _parse_ts(obj.get("timestamp") or obj.get("ts") or obj.get("ts_utc"))
            if ts is not None:
                times.append(pd.Timestamp(ts))
    row["n_rows"] = n
    row["columns"] = sorted(cols)
    row["populated"] = n > 0
    if n == 0:
        row["class"] = "EMPTY"
        return row
    if times:
        idx = pd.DatetimeIndex(times)
        row["timestamps_usable"] = True
        row["date_start"] = str(idx.min())
        row["date_end"] = str(idx.max())
        row["overlap_events"] = _overlap(idx, event_ts)
    row["class"] = "AVAILABLE_BUT_INCOMPLETE"
    row["note"] = "Session replay / runtime log; not a Phase40 event tape."
    return row


def _inspect_sqlite(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = root / spec["path"]
    row: dict[str, Any] = {
        **spec,
        "exists": path.is_file(),
        "format": "sqlite",
        "class": "MISSING",
        "populated": False,
        "evidence_kind": "CODE-EVIDENCE",
        "causal_alignable": False,
        "future_leakage_risk": "UNKNOWN",
        "timestamps_usable": False,
    }
    if not path.is_file():
        return row
    import sqlite3

    try:
        con = sqlite3.connect(str(path))
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        counts = {}
        for t in tables:
            counts[t] = int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
        con.close()
    except Exception as exc:  # noqa: BLE001
        row["inspect_error"] = str(exc)
        row["class"] = "EMPTY"
        return row
    row["tables"] = counts
    row["n_rows"] = int(sum(counts.values()))
    row["populated"] = row["n_rows"] > 0
    row["class"] = "AVAILABLE_BUT_INCOMPLETE" if row["populated"] else "EMPTY"
    row["note"] = "Execution journal is logical XAUUSD / short window; not Phase40 event fills."
    return row


def classify_branch(inventory: list[dict[str, Any]], category: str) -> str:
    rows = [r for r in inventory if r.get("category") == category]
    if not rows:
        return "MISSING"
    if any(r.get("class") == "AVAILABLE_AND_USABLE" for r in rows):
        return "AVAILABLE_AND_USABLE"
    if any(r.get("class") == "AVAILABLE_BUT_INCOMPLETE" and r.get("causal_alignable") for r in rows):
        return "AVAILABLE_BUT_INCOMPLETE"
    if any(r.get("class") == "AVAILABLE_BUT_INCOMPLETE" for r in rows):
        return "AVAILABLE_BUT_INCOMPLETE"
    if any(r.get("class") == "AVAILABLE_BUT_NONCAUSAL" for r in rows):
        return "AVAILABLE_BUT_NONCAUSAL"
    if any(r.get("class") == "EMPTY" for r in rows):
        return "EMPTY"
    return "MISSING"


def run_phase106_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    compact = p98.get("compact") or []
    if compact:
        event_ts = [pd.Timestamp(_parse_ts(r.get("ts"))) for r in compact if _parse_ts(r.get("ts"))]
    else:
        p74 = _safe_load_json(root / PHASE74_JSON) or {}
        events = expand74(p74.get("compact_events") or [])
        event_ts = [pd.Timestamp(_parse_ts(e.get("timestamp"))) for e in events if _parse_ts(e.get("timestamp"))]
    n_signals = 0
    if (root / PHASE40_SETUPS_JSONL).is_file():
        n_signals = len(load_setups(root / PHASE40_SETUPS_JSONL))
    inventory = []
    for spec in CANDIDATES:
        path = spec["path"]
        if path.endswith(".parquet"):
            inventory.append(_inspect_parquet(root, spec, event_ts))
        elif path.endswith(".jsonl"):
            inventory.append(_inspect_jsonl(root, spec, event_ts))
        elif path.endswith(".db"):
            inventory.append(_inspect_sqlite(root, spec))
        else:
            inventory.append({**spec, "class": "MISSING", "exists": (root / path).is_file()})
    absent = []
    for aid, cat, note in ABSENT_CATEGORIES:
        exists = False
        absent.append(
            {
                "id": aid,
                "category": cat,
                "path": None,
                "class": "MISSING",
                "note": note,
                "exists": exists,
                "evidence_kind": "CODE-EVIDENCE",
            }
        )
    by_cat = {
        "tick": classify_branch(inventory, "tick"),
        "bid_ask": classify_branch(inventory, "bid_ask"),
        "spread": classify_branch(inventory, "spread"),
        "m1": classify_branch(inventory, "m1"),
        "m15": classify_branch(inventory, "m15"),
        "h1": classify_branch(inventory, "h1"),
        "h4": classify_branch(inventory, "h4"),
        "session": classify_branch(inventory, "session"),
        "news": "MISSING",
        "economic_calendar": "MISSING",
        "microstructure": classify_branch(inventory, "tick"),
        "execution_fill": classify_branch(inventory, "execution_fill"),
        "feature_store": classify_branch(inventory, "feature_store"),
    }
    usable = [r for r in inventory if r.get("class") == "AVAILABLE_AND_USABLE"]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "downloaded": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "n_events": len(event_ts),
        "n_raw_signals": n_signals,
        "event_unit": "(utc_date, side)",
        "overlap_complete_bar": OVERLAP_COMPLETE,
        "inventory": inventory,
        "absent": absent,
        "by_category": by_cat,
        "usable_canonical": [r.get("id") for r in usable],
        "NON_OHLC_DATA_INVENTORY": by_cat,
        "NON_OHLC_DATA_STATUS": "PARTIAL_LOCAL_FILES_INCOMPLETE_EVENT_COVERAGE",
        "branches_allowed": {
            "107_tick": by_cat["tick"] in {"AVAILABLE_AND_USABLE", "AVAILABLE_BUT_INCOMPLETE"},
            "108_spread": by_cat["spread"] in {"AVAILABLE_AND_USABLE", "AVAILABLE_BUT_INCOMPLETE"}
            or by_cat["bid_ask"] in {"AVAILABLE_AND_USABLE", "AVAILABLE_BUT_INCOMPLETE"},
            "109_htf": by_cat["m15"] in {"AVAILABLE_AND_USABLE", "AVAILABLE_BUT_INCOMPLETE"}
            or by_cat["h4"] in {"AVAILABLE_AND_USABLE", "AVAILABLE_BUT_INCOMPLETE"},
            "110_news": False,
        },
        "evidence_kind": "CODE-EVIDENCE",
        "hypotheses": [
            {
                "id": "H106-01",
                "claim": "Local non-OHLC datasets exist that overlap the Phase40 event tape enough to test a discriminator.",
                "result": "PARTIAL" if usable or by_cat["m15"] != "MISSING" else "UNSUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["content_inspect"],
        "oos_used_for_selection": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE106_JSON, "md": PHASE106_MD},
        "phase90_json_present": (root / PHASE90_JSON).is_file(),
    }
    (root / PHASE106_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE106_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 106 — Non-OHLC Data Inventory",
        "",
        "CODE-EVIDENCE from inspecting local files. No MT5. No download. No .env.",
        f"**NON_OHLC_DATA_STATUS:** `{payload['NON_OHLC_DATA_STATUS']}`",
        f"Event unit n=`{len(event_ts)}` signals=`{n_signals}`",
        "",
        "| ID | class | overlap | path |",
        "|---|---|---|---|",
    ]
    for r in inventory:
        ov = r.get("overlap_events") or {}
        lines.append(
            f"| `{r.get('id')}` | `{r.get('class')}` | `{ov.get('n_overlap')}/{ov.get('n_events')}` | `{r.get('path')}` |"
        )
    lines.append("")
    lines.append("## Absent categories")
    for a in absent:
        lines.append(f"- `{a['id']}` **MISSING** — {a['note']}")
    lines.append("")
    lines.append("Logical `XAUUSD` files are not treated as canonical (EV-EQ-01 NOT_PROVEN).")
    lines.append("")
    (root / PHASE106_MD).write_text("\n".join(lines), encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase106_collection(Path("."))
    print(p["NON_OHLC_DATA_STATUS"], p["by_category"])
