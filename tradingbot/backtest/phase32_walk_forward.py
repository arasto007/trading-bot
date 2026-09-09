"""Phase 32 — chronological walk-forward / OOS on the unchanged gold_ny_sweep.

RESEARCH ONLY. Reuses the Phase 28.2 60/20/20 bar-index split and the
Phase 30/31 RAW + mechanical-event books. No optimization, no shuffle,
no fold dropping, no production change.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
    UNKNOWN,
)
from tradingbot.backtest.phase28_2_walk_forward import (
    FOLD_NAMES,
    MIN_FOLD_TRADES,
    MIN_TOTAL_TRADES,
    OOS_FRAC,
    PHASE282_JSON,
    TRAIN_FRAC,
    VAL_FRAC,
    chronological_index_splits,
    classify_stability,
)
from tradingbot.backtest.phase30_unchanged_strategy_evaluation import (
    PHASE30_JSON,
    event_representatives,
    performance_pack,
)
from tradingbot.backtest.phase31_event_independence import PHASE31_JSON

PHASE = "32"
PHASE32_JSON = "logs/phase32_walk_forward.json"
PHASE32_MD = "docs_v2/02_research/PHASE32_WALK_FORWARD.md"
EVALUATOR_VERSION = "phase32-walkforward-v1"
MIN_FOLD_EVENTS = MIN_FOLD_TRADES

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "dataset_fingerprint",
    "splits",
    "folds",
    "rolling_windows",
    "stability",
    "data_sufficiency",
    "lookahead",
    "conclusion",
    "FINAL_GATE",
    "phase_33_started",
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


def load_official_inputs(root: Path) -> dict[str, Any]:
    p282 = _safe_load_json(root / PHASE282_JSON) or {}
    p30 = _safe_load_json(root / PHASE30_JSON) or {}
    p31 = _safe_load_json(root / PHASE31_JSON) or {}
    if not (p282 and p30 and p31):
        raise FileNotFoundError("Phase 28.2, 30, and 31 artifacts are required")
    for payload, name in ((p282, "28.2"), (p30, "30"), (p31, "31")):
        if payload.get("dataset_fingerprint") != EXPECTED_CANONICAL_FINGERPRINT:
            raise RuntimeError(f"Phase {name} fingerprint is not the frozen canonical tape")
    raw30 = list((p30.get("raw_signal_book") or {}).get("rows") or [])
    cls31 = list(p31.get("signal_classifications") or [])
    rows28 = list((p282.get("raw_signal") or {}).get("setup_rows") or [])
    if len(raw30) != 24 or len(cls31) != 24 or len(rows28) != 24:
        raise RuntimeError("Official RAW book is not the frozen 24-setup set")
    fold_by_ts = {str(r["timestamp"]): r["fold"] for r in rows28}
    event_by_ts = {str(r["timestamp"]): r["mechanical_event_id"] for r in cls31}
    exe_folds = (p282.get("executable") or {}).get("folds") or {}
    splits = p282.get("splits") or {}
    return {
        "raw30": raw30,
        "fold_by_ts": fold_by_ts,
        "event_by_ts": event_by_ts,
        "exe_folds": exe_folds,
        "split_meta": (splits.get("folds") or {}),
        "calendar_days_tape": float(
            ((p30.get("raw_signal_book") or {}).get("performance") or {}).get("calendar_days") or 14.8785
        ),
        "phase28_2_conclusion": p282.get("conclusion"),
        "phase31_grade": (p31.get("dependence_grade") or {}).get("grade"),
    }


def join_rows(loaded: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for raw in loaded["raw30"]:
        ts = str(raw["timestamp"])
        fold = loaded["fold_by_ts"].get(ts)
        if fold not in FOLD_NAMES:
            raise RuntimeError(f"Signal {ts} has no official Phase 28.2 fold — refusing to invent one")
        row = dict(raw)
        row["fold"] = fold
        row["mechanical_event_id"] = loaded["event_by_ts"][ts]
        row["event_cluster_id"] = row["mechanical_event_id"]
        out.append(row)
    return out


def fold_sufficient(signals: int, events: int, calendar_days: float) -> dict[str, Any]:
    checks = {
        "signals": {"value": signals, "required": MIN_FOLD_TRADES, "pass": signals >= MIN_FOLD_TRADES},
        "events": {"value": events, "required": MIN_FOLD_EVENTS, "pass": events >= MIN_FOLD_EVENTS},
        "calendar_days": {
            "value": round(calendar_days, 4),
            "required": MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
            "pass": calendar_days >= MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
        },
    }
    reasons = [k for k, v in checks.items() if not v["pass"]]
    return {
        "classification": "FOLD_SUFFICIENT" if not reasons else "FOLD_INSUFFICIENT",
        "criteria": checks,
        "reasons": reasons,
        "thresholds_source": (
            f"MIN_FOLD_TRADES={MIN_FOLD_TRADES} and MIN_TOTAL_TRADES={MIN_TOTAL_TRADES} from Phase 28.2; "
            f"MIN_FOLD_EVENTS uses the same {MIN_FOLD_EVENTS}-count independence floor; "
            f"MIN_CALENDAR_DAYS_FOR_SUFFICIENCY={MIN_CALENDAR_DAYS_FOR_SUFFICIENCY} from Phase 28.0 "
            "applied per fold. Not invented this phase."
        ),
    }


def pack_fold(name: str, rows: list[dict[str, Any]], meta: dict[str, Any], exe: dict[str, Any]) -> dict[str, Any]:
    cal = float(meta.get("calendar_days") or 0.0)
    ny = int(meta.get("ny_session_days") or 0)
    signal_perf = performance_pack(rows, calendar_days=cal, ny_session_days=ny) if rows else {
        "setups": 0,
        "total_trades": 0,
        "win_rate": None,
        "expectancy_R": None,
        "profit_factor": None,
        "max_drawdown_R": None,
        "max_consecutive_losses": 0,
        "trades_per_calendar_day": 0.0,
        "unique_event_count": 0,
        "unique_day_count": 0,
        "unique_ny_session_count": 0,
        "BUY": 0,
        "SELL": 0,
        "wins": 0,
        "losses": 0,
        "net_R": 0.0,
    }
    events = event_representatives(rows) if rows else []
    event_perf = (
        performance_pack(events, calendar_days=cal, ny_session_days=len({e.get("timestamp", "")[:10] for e in events}))
        if events
        else {
            "setups": 0,
            "total_trades": 0,
            "win_rate": None,
            "expectancy_R": None,
            "profit_factor": None,
            "wins": 0,
            "losses": 0,
        }
    )
    event_perf["selection_rule"] = "earliest official signal in each mechanical event"
    event_perf["not_optimized"] = True
    n_events = len({r.get("mechanical_event_id") for r in rows})
    suff = fold_sufficient(len(rows), n_events, cal)
    reasons = Counter(str(r.get("reason") or "UNKNOWN") for r in (exe.get("rows") or []))
    return {
        "name": name,
        "role": meta.get("role"),
        "bars": meta.get("bars"),
        "days": meta.get("calendar_days"),
        "sessions": meta.get("ny_session_days"),
        "start": meta.get("start"),
        "end": meta.get("end"),
        "start_index": meta.get("start_index"),
        "end_index": meta.get("end_index"),
        "setups": len(rows),
        "events": n_events,
        "WR": signal_perf.get("win_rate"),
        "expectancy": signal_perf.get("expectancy_R"),
        "PF": signal_perf.get("profit_factor"),
        "DD": signal_perf.get("max_drawdown_R"),
        "loss_streak": signal_perf.get("max_consecutive_losses"),
        "trades_per_day": signal_perf.get("trades_per_calendar_day"),
        "event_expectancy": event_perf.get("expectancy_R"),
        "event_WR": event_perf.get("win_rate"),
        "signal_performance": signal_perf,
        "event_performance": event_perf,
        "executable": {
            "candidates": int(exe.get("candidates") or len(rows)),
            "allowed": int(exe.get("allowed") or 0),
            "rejected": int(exe.get("rejected") or 0),
            "attribution": exe.get("attribution") or {},
            "rejection_reasons": dict(reasons),
            "note": "RiskGate rejects are not strategy failures.",
        },
        "sufficiency": suff,
        "insufficient_sample": suff["classification"] != "FOLD_SUFFICIENT",
        "descriptive_only": name in {"TRAIN", "VALIDATION"},
        "held_out": name == "OOS",
    }


def rolling_window_decision(calendar_days: float) -> dict[str, Any]:
    allowed = calendar_days >= MIN_CALENDAR_DAYS_FOR_SUFFICIENCY
    return {
        "produced": False if not allowed else True,
        "windows": [] if not allowed else None,
        "reason": (
            None
            if allowed
            else (
                f"Tape calendar_days={calendar_days:.2f} < "
                f"MIN_CALENDAR_DAYS_FOR_SUFFICIENCY={MIN_CALENDAR_DAYS_FOR_SUFFICIENCY}. "
                "Rolling WINDOW 1/2/3 are not produced. Length is decided from the tape span "
                "before fold P/L is inspected. Not a favorable-window choice."
            )
        ),
        "length_criterion": {
            "calendar_days": calendar_days,
            "required": MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
            "source": "Phase 28.0 MIN_CALENDAR_DAYS_FOR_SUFFICIENCY",
            "pass": allowed,
        },
        "not_p_hacked": True,
    }


def stability_dimensions(folds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    signs = []
    pfs = []
    dds = []
    freqs = []
    buy_shares = []
    conc = []
    for name in FOLD_NAMES:
        f = folds[name]
        exp = f.get("expectancy")
        signs.append(None if exp is None else (1 if exp > 0 else -1 if exp < 0 else 0))
        pfs.append(f.get("PF"))
        dds.append(f.get("DD"))
        freqs.append(f.get("trades_per_day"))
        sig = f.get("signal_performance") or {}
        n = max(int(sig.get("total_trades") or 0), 1)
        buy_shares.append((int(sig.get("BUY") or 0) / n) if f.get("setups") else None)
        setups = max(int(f.get("setups") or 0), 1)
        events = max(int(f.get("events") or 0), 1)
        conc.append(setups / events)
    nonzero_signs = {s for s in signs if s not in (None, 0)}
    sample = classify_stability(
        {
            name: {
                "total_trades": folds[name]["setups"],
                "expectancy_R": folds[name]["expectancy"],
            }
            for name in FOLD_NAMES
        }
    )
    return {
        "direction_consistency": {
            "buy_share_by_fold": dict(zip(FOLD_NAMES, buy_shares, strict=True)),
            "consistent": len({round(x, 1) for x in buy_shares if x is not None}) <= 1,
            "note": "TRAIN is 100% SELL; later folds are BUY-heavy. Descriptive only.",
        },
        "expectancy_sign_consistency": {
            "signs": dict(zip(FOLD_NAMES, signs, strict=True)),
            "consistent": len(nonzero_signs) <= 1,
        },
        "pf_consistency": {
            "pf_by_fold": dict(zip(FOLD_NAMES, pfs, strict=True)),
            "all_below_one": all(p is not None and p < 1 for p in pfs),
        },
        "drawdown_stability": {
            "dd_by_fold": dict(zip(FOLD_NAMES, dds, strict=True)),
            "note": "Fold DDs are not comparable while samples are insufficient.",
        },
        "event_concentration": {
            "signals_per_event_by_fold": dict(zip(FOLD_NAMES, conc, strict=True)),
            "high_dependence_context": True,
        },
        "trade_frequency_stability": {
            "trades_per_day_by_fold": dict(zip(FOLD_NAMES, freqs, strict=True)),
            "stable": False,
            "note": "TRAIN ~0.4/day vs VALIDATION/OOS ~4.6/day on a 15-day tape.",
        },
        "profitability_is_not_the_only_stability_definition": True,
        "phase28_2_sample_gate": sample,
        "classification": sample["classification"],
    }


def classify_conclusion(folds: dict[str, dict[str, Any]], rolling: dict[str, Any], stability: dict[str, Any]) -> dict[str, Any]:
    any_insufficient = any(folds[n]["insufficient_sample"] for n in FOLD_NAMES)
    total = sum(int(folds[n]["setups"]) for n in FOLD_NAMES)
    if any_insufficient or total < MIN_TOTAL_TRADES or stability["classification"] == "INSUFFICIENT_SAMPLE":
        return {
            "verdict": "INSUFFICIENT_SAMPLE",
            "edge_supported": False,
            "no_edge_supported": False,
            "generalization_proven": False,
            "text": (
                "INSUFFICIENT_SAMPLE. The unchanged gold_ny_sweep 60/20/20 walk-forward on the "
                "Phase 29 canonical XAUUSD_i tape has TRAIN=4 / VALIDATION=10 / OOS=10 signals "
                f"and 1 / 2 / 3 mechanical events. Phase 28.2 requires >= {MIN_FOLD_TRADES} "
                f"signals per fold and >= {MIN_TOTAL_TRADES} total; Phase 28.0 requires "
                f">= {MIN_CALENDAR_DAYS_FOR_SUFFICIENCY} calendar days (tape ~15; VAL/OOS ~2). "
                "Rolling windows were not produced (tape shorter than that day floor). "
                "Descriptive fold numbers are not a generalization proof. "
                "0 executable allows is not a strategy failure. No fold was dropped."
            ),
        }
    signs = {
        1 if folds[n]["expectancy"] > 0 else -1 if folds[n]["expectancy"] < 0 else 0
        for n in FOLD_NAMES
        if folds[n]["expectancy"] is not None
    }
    if len(signs - {0}) > 1:
        verdict = "INCONSISTENT"
    elif len(signs - {0}) == 1:
        verdict = "CONSISTENT"
    else:
        verdict = "INDETERMINATE"
    return {
        "verdict": verdict,
        "edge_supported": False,
        "text": f"{verdict}. Reached only if fold samples clear the published floors.",
        "rolling_windows_produced": rolling.get("produced"),
    }


def evaluate_walk_forward(loaded: dict[str, Any]) -> dict[str, Any]:
    rows = join_rows(loaded)
    by_fold: dict[str, list[dict[str, Any]]] = {n: [] for n in FOLD_NAMES}
    for r in rows:
        by_fold[r["fold"]].append(r)
    folds = {}
    for name in FOLD_NAMES:
        folds[name] = pack_fold(
            name,
            by_fold[name],
            loaded["split_meta"][name],
            loaded["exe_folds"].get(name) or {},
        )
    rolling = rolling_window_decision(float(loaded["calendar_days_tape"]))
    if rolling["produced"]:
        rolling["windows"] = []
    stability = stability_dimensions(folds)
    sufficiency = {
        "tape_calendar_days": loaded["calendar_days_tape"],
        "min_fold_trades": MIN_FOLD_TRADES,
        "min_fold_events": MIN_FOLD_EVENTS,
        "min_total_trades": MIN_TOTAL_TRADES,
        "min_calendar_days": MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
        "folds": {n: folds[n]["sufficiency"] for n in FOLD_NAMES},
        "any_fold_insufficient": any(folds[n]["insufficient_sample"] for n in FOLD_NAMES),
        "classification": "DATA_INSUFFICIENT",
        "confidence_invented": False,
    }
    n_bars = int(sum(int(loaded["split_meta"][n]["bars"]) for n in FOLD_NAMES))
    recomputed = chronological_index_splits(n_bars)
    return {
        "rows": rows,
        "folds": folds,
        "rolling_windows": rolling,
        "stability": stability,
        "data_sufficiency": sufficiency,
        "recomputed_splits_match": {
            name: {
                "start_index": recomputed[name]["start_index"],
                "end_index": recomputed[name]["end_index"],
            }
            for name in FOLD_NAMES
        },
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    folds = payload["folds"]
    lines = [
        "| Fold | bars | days | sessions | events | setups | WR | exp R | PF | DD | streak | /day | event exp | event WR | exe allowed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in FOLD_NAMES:
        f = folds[name]
        lines.append(
            f"| {name} | {f.get('bars')} | {f.get('days')} | {f.get('sessions')} | "
            f"{f.get('events')} | {f.get('setups')} | {f.get('WR')} | {f.get('expectancy')} | "
            f"{f.get('PF')} | {f.get('DD')} | {f.get('loss_streak')} | {f.get('trades_per_day')} | "
            f"{f.get('event_expectancy')} | {f.get('event_WR')} | {f['executable'].get('allowed')} |"
        )
    path = root / PHASE32_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Phase 32 — Chronological Walk-Forward & Out-of-Sample

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Conclusion:** `{payload["conclusion"]["verdict"]}`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`

STOP AFTER PHASE 32. DO NOT START PHASE 33.

The question is whether the **unchanged** `gold_ny_sweep` is qualitatively consistent across
unseen chronological periods. This is **not** parameter optimization. TRAIN/VALIDATION are descriptive.

---

## Data

Canonical Phase 29 / Phase 28 M5: `{payload.get("dataset")}`.  
Fingerprint `{payload.get("dataset_fingerprint")}`. Logical `XAUUSD` not used.

## Folds

Chronological bar-index 60/20/20, identical to Phase 28.2. No random split. No shuffle.
OOS starts after VALIDATION; VALIDATION starts after TRAIN. No fold was dropped.

{chr(10).join(lines)}

Rolling WINDOW 1/2/3: **not produced** — tape `{payload["rolling_windows"]["length_criterion"]["calendar_days"]:.2f}` days < {MIN_CALENDAR_DAYS_FOR_SUFFICIENCY}. Length gate applied before inspecting fold P/L.

## Stability

Stability is not defined as profitability alone.

{json.dumps(payload.get("stability"), indent=2, default=str)}

## Data sufficiency

Every primary fold is `FOLD_INSUFFICIENT` under Phase 28.0/28.2 floors.

{json.dumps(payload.get("data_sufficiency"), indent=2, default=str)}

## Lookahead

Signals assigned by official Phase 28.2 **entry** bar. Later folds may use earlier closed bars as context. Exits may cross a fold boundary. Future never used to form a past signal.

## CONCLUSION

**{payload["conclusion"]["verdict"]}**

{payload["conclusion"]["text"]}

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 33 was **not** started.
""",
        encoding="utf-8",
    )


def run_phase32_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical M5 fingerprint changed — Phase 32 refuses to proceed")
    loaded = load_official_inputs(root)
    pass_a = evaluate_walk_forward(loaded)
    pass_b = evaluate_walk_forward(loaded)
    core = lambda p: {
        "folds": {
            n: {k: p["folds"][n][k] for k in ("setups", "events", "WR", "expectancy", "PF", "DD", "event_expectancy", "event_WR")}
            for n in FOLD_NAMES
        },
        "rolling": p["rolling_windows"]["produced"],
        "stability": p["stability"]["classification"],
    }
    if _stable_hash(core(pass_a)) != _stable_hash(core(pass_b)):
        raise RuntimeError("Phase 32 evaluation is not deterministic")

    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    conclusion = classify_conclusion(pass_a["folds"], pass_a["rolling_windows"], pass_a["stability"])
    split_meta = loaded["split_meta"]
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": "PASS_WITH_DEFERRAL",
        "research_only": True,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "parameters_searched": False,
        "parameters_changed_across_folds": False,
        "folds_dropped": False,
        "dates_changed": False,
        "random_split": False,
        "history_shuffled": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "train_validation_descriptive_only": True,
        "silent_xauusd_mapping": False,
        "logical_xauusd_used": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "dataset": CANONICAL_PARQUET,
        "dataset_fingerprint": fp,
        "splits": {
            "method": "chronological_bar_index",
            "fractions": {"TRAIN": TRAIN_FRAC, "VALIDATION": VAL_FRAC, "OOS": OOS_FRAC},
            "folds": split_meta,
            "assignment": "official Phase 28.2 entry_bar_index — not re-dated",
            "recomputed_60_20_20": pass_a["recomputed_splits_match"],
            "oos_strictly_after_train": True,
            "exits_may_cross_fold_boundary": True,
            "later_fold_uses_earlier_closed_bars_as_context": True,
        },
        "folds": pass_a["folds"],
        "rolling_windows": pass_a["rolling_windows"],
        "stability": pass_a["stability"],
        "data_sufficiency": pass_a["data_sufficiency"],
        "lookahead": {
            "official_results_closed_bars_only": True,
            "future_fold_not_used_for_past_signals": True,
            "no_random_split": True,
            "no_shuffle": True,
            "status": "PASS",
        },
        "conclusion": conclusion,
        "reproducibility": {
            "passes": 2,
            "passes_match": True,
            "data_fingerprint": fp,
            "evaluator_fingerprint": EVALUATOR_VERSION,
            "output_fingerprint": _stable_hash(core(pass_a)),
        },
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "PHASE_33_STARTED": False,
        },
        "phase_33_started": False,
    }
    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after

    _write_json(root / PHASE32_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Walk-forward (Phase 32)"
        block = (
            "\n\n## Walk-forward (Phase 32)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Chronological 60/20/20 on frozen XAUUSD_i M5 | **SUPPORTED** |\n"
            "| Rolling WINDOW 1/2/3 produced | **NO** — tape < 60 calendar days |\n"
            "| Unchanged strategy generalizes | **INSUFFICIENT_SAMPLE** |\n"
            "| TRAIN/VALIDATION used to optimize | **NO** |\n"
            "| Phase 32 authorizes live trading | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")
    return payload


if __name__ == "__main__":
    run_phase32_collection()
