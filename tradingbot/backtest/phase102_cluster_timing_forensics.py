"""Phase 102 — event cluster / signal timing.

EVENT is the unit. 2847 jsonl rows are members, not independent samples.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from datetime import datetime, timezone

from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    event_key,
    _git_head,
    _median,
    _parse_ts,
    _utc_now,
    load_setups,
)
from tradingbot.backtest.phase68_exit_forensics import load_frozen_ohlc
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, expand74
from tradingbot.backtest.phase90_profit_giveback_path_forensics import prepare_events
from tradingbot.backtest.phase98_first_favorable_state import CD, EF, PHASE98_JSON, _rate, confirmed_sep, majority_sep

PHASE = "102"
PHASE102_JSON = "logs/phase102_cluster_timing_forensics.json"
PHASE102_MD = "docs/PHASE102_CLUSTER_TIMING_FORENSICS.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "CLUSTER_EARLY_WARNING",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        value = _parse_ts(value)
        if value is None:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def run_phase102_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    events = prepare_events(root, expand74(p74.get("compact_events") or []))
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    groups: dict[tuple[str, str], list] = {}
    for s in signals:
        groups.setdefault(event_key(s), []).append(s)
    df, _fp = load_frozen_ohlc(root)
    by_ts = {r.get("ts"): r for r in (p98.get("compact") or [])}
    rows = []
    for e in events:
        r = by_ts.get(e.get("timestamp")) or {}
        key = event_key({"timestamp": e.get("timestamp"), "side": e.get("side")})
        members = sorted(groups.get(key) or [], key=lambda m: str(m.get("timestamp")))
        fav_bar = (r.get("anatomy") or {}).get("first_fav_bar")
        retrace_bar = ((r.get("anatomy") or {}).get("retrace") or {}).get("bar")
        mfe_state = (r.get("states") or {}).get("0.5") or {}
        mfe_bar = mfe_state.get("bar")
        fav_ts = None
        mfe_ts = None
        ret_ts = None
        if df is not None:
            if fav_bar is not None and 0 <= int(fav_bar) < len(df):
                fav_ts = _as_utc(df.index[int(fav_bar)])
            if mfe_bar is not None and 0 <= int(mfe_bar) < len(df):
                mfe_ts = _as_utc(df.index[int(mfe_bar)])
            if retrace_bar is not None and 0 <= int(retrace_bar) < len(df):
                ret_ts = _as_utc(df.index[int(retrace_bar)])
        n_before_fav = 0
        n_before_mfe = 0
        n_during_giveback = 0
        sides = set()
        regimes = set()
        gaps = []
        prev = None
        for m in members:
            ts = _as_utc(_parse_ts(m.get("timestamp")))
            sides.add(str(m.get("direction") or m.get("side") or "").upper())
            regimes.add(str(m.get("regime") or ""))
            if ts is not None and prev is not None:
                gaps.append((ts - prev).total_seconds() / 60.0)
            if ts is not None:
                prev = ts
            if fav_ts is not None and ts is not None and ts < fav_ts:
                n_before_fav += 1
            if mfe_ts is not None and ts is not None and ts < mfe_ts:
                n_before_mfe += 1
            if ret_ts is not None and ts is not None and ts >= ret_ts:
                n_during_giveback += 1
        rows.append(
            {
                "ts": e.get("timestamp"),
                "path_class": r.get("path_class"),
                "fold": r.get("fold"),
                "n_sig": len(members),
                "n_before_fav": n_before_fav,
                "n_before_mfe": n_before_mfe,
                "n_during_giveback": n_during_giveback,
                "side_consistent": len(sides) <= 1,
                "regime_consistent": len(regimes) <= 1,
                "median_gap_min": _median(gaps),
                "repeat_before_fav": n_before_fav >= 2,
                "repeat_during_giveback": n_during_giveback >= 2,
                "is_CD": r.get("path_class") in CD,
                "is_EF": r.get("path_class") in EF,
            }
        )
    cd = [x for x in rows if x.get("is_CD")]
    ef = [x for x in rows if x.get("is_EF")]
    feats = ("repeat_before_fav", "repeat_during_giveback", "side_consistent", "regime_consistent")
    feat_rows = {}
    separators = []
    for feat in feats:
        def fold_sep(fold: str, f=feat) -> str:
            return majority_sep(
                _rate([x for x in cd if x.get("fold") == fold], f).get("rate"),
                _rate([x for x in ef if x.get("fold") == fold], f).get("rate"),
            )

        tr, va = fold_sep("TRAIN"), fold_sep("VALIDATION")
        confirmed = confirmed_sep(
            _rate([x for x in cd if x.get("fold") == "TRAIN"], feat).get("rate"),
            _rate([x for x in ef if x.get("fold") == "TRAIN"], feat).get("rate"),
            _rate([x for x in cd if x.get("fold") == "VALIDATION"], feat).get("rate"),
            _rate([x for x in ef if x.get("fold") == "VALIDATION"], feat).get("rate"),
        )
        feat_rows[feat] = {
            "CD": _rate(cd, feat),
            "EF": _rate(ef, feat),
            "TRAIN_sep": tr,
            "VAL_sep": va,
            "TRAIN_VAL_confirmed": confirmed,
            "median_n_before_fav_CD": _median([float(x.get("n_before_fav") or 0) for x in cd]),
            "median_n_before_fav_EF": _median([float(x.get("n_before_fav") or 0) for x in ef]),
        }
        if confirmed:
            separators.append(feat)
    warning = "NOT_ESTABLISHED" if not separators else "CANDIDATE_CLUSTER_TIMING"
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
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "n_events": len(rows),
        "n_raw_signals": len(signals),
        "signals_not_independent": True,
        "event_unit": "(utc_date, side)",
        "features": feat_rows,
        "separators_train_val": separators,
        "CLUSTER_EARLY_WARNING": warning,
        "median_n_before_fav_CD": _median([float(x.get("n_before_fav") or 0) for x in cd]),
        "median_n_before_fav_EF": _median([float(x.get("n_before_fav") or 0) for x in ef]),
        "evidence_kind": "FROZEN-DATA-EVIDENCE",
        "hypotheses": [
            {
                "id": "H102-01",
                "claim": "Repeated signals before first favorable excursion warn of giveback vs continuation.",
                "result": warning,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["cluster_timing"],
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
        "artifacts": {"json": PHASE102_JSON, "md": PHASE102_MD},
    }
    (root / PHASE102_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE102_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE102_MD).write_text(
        "\n".join(
            [
                "# Phase 102 — Event Cluster / Signal Timing",
                "",
                "FROZEN-DATA-EVIDENCE. Event unit only. 2847 rows are not independent.",
                f"**CLUSTER_EARLY_WARNING:** `{warning}`",
                f"median signals before first fav CD=`{payload['median_n_before_fav_CD']}` EF=`{payload['median_n_before_fav_EF']}`",
                f"TRAIN+VAL separators: `{separators}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase102_collection(Path("."))
    print(p["CLUSTER_EARLY_WARNING"], p["n_raw_signals"], p["n_events"])
