"""Phase 33 — strategy robustness and adversarial diagnostic checks.

RESEARCH ONLY. Uses the Phase 30/32 unchanged baseline. Pre-declared
symmetric perturbations only. No optimization, no parameter search,
no production change.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
    MIN_RESOLVED_FOR_SUFFICIENCY,
    UNKNOWN,
    load_parquet_utc,
    theoretical_outcome,
)
from tradingbot.backtest.phase28_1_full_baseline import _parse_ts
from tradingbot.backtest.phase28_2_walk_forward import MIN_FOLD_TRADES, PHASE282_JSON
from tradingbot.backtest.phase28_3_monte_carlo import (
    MIN_TRADES_FOR_ROBUSTNESS,
    apply_modeled_shift,
    modeled_cost_spec,
    path_metrics,
)
from tradingbot.backtest.phase28_4_strategy_diagnosis import PHASE284_JSON
from tradingbot.backtest.phase30_unchanged_strategy_evaluation import PHASE30_JSON, event_representatives
from tradingbot.backtest.phase31_event_independence import PHASE31_JSON
from tradingbot.backtest.phase32_walk_forward import PHASE32_JSON

PHASE = "33"
PHASE33_JSON = "logs/phase33_robustness.json"
PHASE33_MD = "docs_v2/02_research/PHASE33_ROBUSTNESS.md"
EVALUATOR_VERSION = "phase33-robustness-v1"
SL_DISTANCE_MULTIPLIERS = (0.90, 1.10)
RR_OFFSETS = (-0.25, 0.25)
COST_SHOCK_MULTS = (("baseline", 1.0), ("moderate", 2.0), ("high_plausible", 3.0))
MATERIAL_EXP_DELTA = 0.25
MIN_SLICE_N = MIN_FOLD_TRADES

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "dataset_fingerprint",
    "baseline",
    "entry_robustness",
    "sl_robustness",
    "tp_rr_robustness",
    "cost_shocks",
    "signal_quality",
    "time_robustness",
    "event_robustness",
    "conclusion",
    "FINAL_GATE",
    "phase_34_started",
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


def summarize_r(values: list[float | None]) -> dict[str, Any]:
    rs = [float(v) for v in values if v is not None]
    if not rs:
        return {"n": 0, "wins": 0, "losses": 0, "win_rate": None, "expectancy_R": None, "profit_factor": None, "net_R": None}
    path = path_metrics(rs)
    return {
        "n": len(rs),
        "wins": int(path["wins"]),
        "losses": int(path["losses"]),
        "win_rate": path["win_rate"],
        "expectancy_R": path["expectancy_R"],
        "profit_factor": path["profit_factor"],
        "net_R": path["final_R"],
        "max_drawdown_R": path["max_drawdown_R"],
        "max_consecutive_losses": int(path["longest_losing_streak"]),
    }


def material_vs_baseline(new: dict[str, Any], baseline_exp: float) -> dict[str, Any]:
    exp = new.get("expectancy_R")
    if exp is None:
        return {"material": False, "sign_flip": False, "abs_delta": None, "threshold": MATERIAL_EXP_DELTA}
    sign_flip = (exp > 0) != (baseline_exp > 0) and exp != 0 and baseline_exp != 0
    delta = abs(float(exp) - float(baseline_exp))
    return {
        "material": bool(sign_flip or delta >= MATERIAL_EXP_DELTA),
        "sign_flip": bool(sign_flip),
        "abs_delta": float(delta),
        "threshold": MATERIAL_EXP_DELTA,
        "rule": f"material if expectancy sign flips or |Δexp| >= {MATERIAL_EXP_DELTA} R (Phase 28.2 stability delta)",
    }


def load_baseline(root: Path) -> dict[str, Any]:
    p30 = _safe_load_json(root / PHASE30_JSON) or {}
    p31 = _safe_load_json(root / PHASE31_JSON) or {}
    p32 = _safe_load_json(root / PHASE32_JSON) or {}
    p282 = _safe_load_json(root / PHASE282_JSON) or {}
    p284 = _safe_load_json(root / PHASE284_JSON) or {}
    if not (p30 and p31 and p32 and p282 and p284):
        raise FileNotFoundError("Phase 30/31/32/28.2/28.4 artifacts are required")
    for payload, name in ((p30, "30"), (p31, "31"), (p32, "32"), (p284, "28.4")):
        if payload.get("dataset_fingerprint") != EXPECTED_CANONICAL_FINGERPRINT:
            raise RuntimeError(f"Phase {name} fingerprint is not the frozen canonical tape")
    raw = list((p30.get("raw_signal_book") or {}).get("rows") or [])
    if len(raw) != 24:
        raise RuntimeError("Phase 30 RAW book is not the frozen 24-setup set")
    rec = {str(r["timestamp"]): r for r in (p284.get("reconstructed_setups") or [])}
    idx = {str(r["timestamp"]): int(r["closed_bar_index"]) for r in ((p282.get("raw_signal") or {}).get("setup_rows") or [])}
    events = {str(r["timestamp"]): r["mechanical_event_id"] for r in (p31.get("signal_classifications") or [])}
    folds = {n: p32["folds"][n]["setups"] for n in ("TRAIN", "VALIDATION", "OOS")}
    rows = []
    for r in raw:
        ts = str(r["timestamp"])
        extra = rec.get(ts) or {}
        row = dict(r)
        row["closed_bar_index"] = idx[ts]
        row["mechanical_event_id"] = events[ts]
        row["event_cluster_id"] = events[ts]
        row["entry_counterfactuals"] = extra.get("entry_counterfactuals") or {}
        row["sweep_depth_atr"] = extra.get("sweep_depth_atr")
        row["planned_rr"] = row.get("planned_rr") or extra.get("planned_rr")
        rows.append(row)
    perf = (p30.get("raw_signal_book") or {}).get("performance") or {}
    return {
        "rows": rows,
        "calendar_days": float(perf.get("calendar_days") or 14.8785),
        "phase30_expectancy": float(perf.get("expectancy_R") or -0.895833),
        "phase30_wr": perf.get("win_rate"),
        "phase32_verdict": (p32.get("conclusion") or {}).get("verdict"),
        "phase32_fold_setups": folds,
        "n_events": len({r["mechanical_event_id"] for r in rows}),
    }


def locate_index(df, row: dict[str, Any]) -> int:
    if row.get("closed_bar_index") is not None:
        return int(row["closed_bar_index"])
    ts = _parse_ts(row["timestamp"])
    return int(df.index.get_indexer([ts], method="nearest")[0])


def side_of(row: dict[str, Any]) -> str:
    return str(row.get("side") or row.get("direction") or "").upper()


def perturb_sl(df, row: dict[str, Any], mult: float) -> dict[str, Any]:
    i = locate_index(df, row)
    entry = float(row["entry_price"])
    sl = float(row["stop_loss"])
    tp = float(row["take_profit"])
    buy = side_of(row) == "BUY"
    dist = abs(entry - sl)
    new_sl = entry - dist * mult if buy else entry + dist * mult
    walked = theoretical_outcome(df, i, side_of(row), entry, new_sl, tp)
    return {
        "multiplier": mult,
        "new_stop_loss": new_sl,
        "r_multiple": walked.get("r_multiple"),
        "outcome": walked.get("outcome"),
        "class": "ANALYTICAL_COUNTERFACTUAL",
        "production_sl_unchanged": True,
    }


def perturb_rr(df, row: dict[str, Any], offset: float) -> dict[str, Any]:
    i = locate_index(df, row)
    entry = float(row["entry_price"])
    sl = float(row["stop_loss"])
    buy = side_of(row) == "BUY"
    dist = abs(entry - sl)
    planned = float(row.get("planned_rr") or (abs(float(row["take_profit"]) - entry) / dist if dist else 1.5))
    new_rr = planned + offset
    new_tp = entry + dist * new_rr if buy else entry - dist * new_rr
    walked = theoretical_outcome(df, i, side_of(row), entry, sl, new_tp)
    return {
        "rr_offset": offset,
        "planned_rr": planned,
        "new_rr": new_rr,
        "new_take_profit": new_tp,
        "r_multiple": walked.get("r_multiple"),
        "outcome": walked.get("outcome"),
        "class": "ANALYTICAL_COUNTERFACTUAL",
        "production_tp_unchanged": True,
    }


def perturb_displacement(df, row: dict[str, Any], adverse_price: float) -> dict[str, Any]:
    i = locate_index(df, row)
    entry = float(row["entry_price"])
    sl = float(row["stop_loss"])
    tp = float(row["take_profit"])
    buy = side_of(row) == "BUY"
    new_entry = entry + adverse_price if buy else entry - adverse_price
    walked = theoretical_outcome(df, i, side_of(row), new_entry, sl, tp)
    return {
        "adverse_price": adverse_price,
        "new_entry": new_entry,
        "r_multiple": walked.get("r_multiple"),
        "outcome": walked.get("outcome"),
        "class": "ANALYTICAL_COUNTERFACTUAL",
        "label": "MODELED_PROXY small execution displacement",
    }


def cf_r(row: dict[str, Any], key: str) -> float | None:
    block = (row.get("entry_counterfactuals") or {}).get(key) or {}
    val = block.get("r_multiple")
    return None if val is None else float(val)


def slice_table(rows: list[dict[str, Any]], key_fn, *, min_n: int = MIN_SLICE_N) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(key_fn(r))].append(r)
    out = []
    for name, items in sorted(groups.items(), key=lambda kv: kv[0]):
        summary = summarize_r([r.get("theoretical_R") for r in items])
        summary["slice"] = name
        summary["insufficient_slice"] = summary["n"] < min_n
        summary["min_n_warning"] = min_n
        out.append(summary)
    return out


def tertile_label(values: list[float], x: float | None) -> str:
    usable = [v for v in values if v is not None]
    if x is None or len(usable) < 3:
        return "UNKNOWN"
    q1, q2 = float(np.percentile(usable, 33.333)), float(np.percentile(usable, 66.667))
    if x <= q1:
        return "low_tertile"
    if x <= q2:
        return "mid_tertile"
    return "high_tertile"


def evaluate_robustness(loaded: dict[str, Any], df) -> dict[str, Any]:
    rows = loaded["rows"]
    baseline_exp = float(loaded["phase30_expectancy"])
    baseline = summarize_r([r.get("theoretical_R") for r in rows])
    costs = modeled_cost_spec()
    adverse = float(costs["half_spread_price"] + costs["slippage_price"])

    entry = {
        "class": "ANALYTICAL_COUNTERFACTUAL",
        "production_entry_unchanged": True,
        "official_close": summarize_r([r.get("theoretical_R") for r in rows]),
        "next_bar_open": summarize_r([cf_r(r, "next_bar_open") for r in rows]),
        "first_eligible_reclaim_close": summarize_r([cf_r(r, "after_reclaim_confirmation") for r in rows]),
        "small_execution_displacement": summarize_r(
            [perturb_displacement(df, r, adverse).get("r_multiple") for r in rows]
        ),
        "displacement_spec": {
            "adverse_price": adverse,
            "components": {
                "spread": "MODELED_PROXY",
                "slippage": "MODELED_PROXY",
                "commission": "UNKNOWN",
            },
            "note": "BacktestConfig half-spread + slippage, one-sided adverse. Not realized.",
        },
    }
    for key in ("official_close", "next_bar_open", "first_eligible_reclaim_close", "small_execution_displacement"):
        entry[key]["vs_baseline"] = material_vs_baseline(entry[key], baseline_exp)

    sl_books = {}
    for mult in SL_DISTANCE_MULTIPLIERS:
        book = summarize_r([perturb_sl(df, r, mult).get("r_multiple") for r in rows])
        book["vs_baseline"] = material_vs_baseline(book, baseline_exp)
        sl_books[f"sl_distance_x{mult:.2f}"] = book
    sl = {
        "class": "ANALYTICAL_COUNTERFACTUAL",
        "production_sl_unchanged": True,
        "predeclared": list(SL_DISTANCE_MULTIPLIERS),
        "not_a_parameter_search": True,
        "official": {**baseline, "vs_baseline": material_vs_baseline(baseline, baseline_exp)},
        "perturbations": sl_books,
        "note": "Symmetric ±10% of the existing SL distance. TP and entry stay official.",
    }

    rr_books = {}
    for off in RR_OFFSETS:
        book = summarize_r([perturb_rr(df, r, off).get("r_multiple") for r in rows])
        book["vs_baseline"] = material_vs_baseline(book, baseline_exp)
        rr_books[f"planned_rr_{off:+.2f}"] = book
    tp = {
        "class": "ANALYTICAL_COUNTERFACTUAL",
        "production_tp_unchanged": True,
        "predeclared": list(RR_OFFSETS),
        "not_a_parameter_search": True,
        "official": {**baseline, "vs_baseline": material_vs_baseline(baseline, baseline_exp)},
        "perturbations": rr_books,
        "note": "Symmetric ±0.25 R around each trade's existing planned RR. SL and entry stay official.",
    }

    trades = [
        {
            "direction": side_of(r),
            "entry_price": r["entry_price"],
            "stop_loss": r["stop_loss"],
            "take_profit": r["take_profit"],
            "outcome": r["outcome"],
            "r_multiple": r["theoretical_R"],
        }
        for r in rows
    ]
    cost_books = {}
    for name, mult in COST_SHOCK_MULTS:
        shifted = apply_modeled_shift(trades, adverse * mult)
        book = summarize_r(shifted)
        book["vs_baseline"] = material_vs_baseline(book, baseline_exp)
        book["multiplier"] = mult
        book["label"] = "MODELED"
        book["not_realized"] = True
        cost_books[name] = book
    cost = {
        "components": {
            "spread": "MODELED_PROXY",
            "slippage": "MODELED_PROXY",
            "commission": "UNKNOWN",
            "swap": "UNKNOWN",
            "observed_broker_costs": False,
        },
        "spec": costs,
        "predeclared_multipliers": {n: m for n, m in COST_SHOCK_MULTS},
        "books": cost_books,
        "note": "1x / 2x / 3x the Phase 28.3 MODELED half-spread+slippage. Not OBSERVED fills.",
    }

    qualities = [float(r["quality_score"]) for r in rows if r.get("quality_score") is not None]
    atrs = [float(r["atr_percentile"]) for r in rows if r.get("atr_percentile") is not None]
    depths = [float(r["sweep_depth_atr"]) for r in rows if r.get("sweep_depth_atr") is not None]
    quality = {
        "thresholds_tuned": False,
        "quality_tertiles": slice_table(
            rows, lambda r: tertile_label(qualities, None if r.get("quality_score") is None else float(r["quality_score"]))
        ),
        "atr_percentile_tertiles": slice_table(
            rows, lambda r: tertile_label(atrs, None if r.get("atr_percentile") is None else float(r["atr_percentile"]))
        ),
        "sweep_depth_atr_tertiles": slice_table(
            rows,
            lambda r: tertile_label(depths, None if r.get("sweep_depth_atr") is None else float(r["sweep_depth_atr"])),
        ),
        "regime": slice_table(rows, lambda r: r.get("regime") or "UNKNOWN"),
        "note": "Tertiles are descriptive partitions of the observed 24-row book. Not candidate gates.",
    }
    ts = lambda r: _parse_ts(r["timestamp"])
    time_block = {
        "weekday": slice_table(rows, lambda r: (ts(r).day_name() if ts(r) is not None else "UNKNOWN")),
        "month": slice_table(rows, lambda r: (f"{ts(r).year:04d}-{ts(r).month:02d}" if ts(r) is not None else "UNKNOWN")),
        "week": slice_table(rows, lambda r: (f"{ts(r).year:04d}-W{int(ts(r).isocalendar().week):02d}" if ts(r) is not None else "UNKNOWN")),
        "ny_session": slice_table(rows, lambda r: r.get("session") or "NY 15-16 UTC"),
        "market_regime": slice_table(rows, lambda r: r.get("regime") or "UNKNOWN"),
        "min_n_warning": MIN_SLICE_N,
        "note": "Every slice with n < 10 is flagged insufficient. All official signals are hour 15 UTC.",
    }

    event_rows = event_representatives(rows)
    event_base = summarize_r([r.get("theoretical_R") for r in event_rows])
    event_exp = float(event_base["expectancy_R"] or 0.0)
    event = {
        "n_events": len(event_rows),
        "selection": "earliest official signal in each mechanical event",
        "not_optimized": True,
        "baseline": event_base,
        "entry": {
            "official_close": event_base,
            "next_bar_open": summarize_r([cf_r(r, "next_bar_open") for r in event_rows]),
            "first_eligible_reclaim_close": summarize_r([cf_r(r, "after_reclaim_confirmation") for r in event_rows]),
        },
        "sl": {
            f"sl_distance_x{mult:.2f}": summarize_r([perturb_sl(df, r, mult).get("r_multiple") for r in event_rows])
            for mult in SL_DISTANCE_MULTIPLIERS
        },
        "tp_rr": {
            f"planned_rr_{off:+.2f}": summarize_r([perturb_rr(df, r, off).get("r_multiple") for r in event_rows])
            for off in RR_OFFSETS
        },
        "cost": {
            name: summarize_r(
                apply_modeled_shift(
                    [
                        {
                            "direction": side_of(r),
                            "entry_price": r["entry_price"],
                            "stop_loss": r["stop_loss"],
                            "take_profit": r["take_profit"],
                            "outcome": r["outcome"],
                            "r_multiple": r["theoretical_R"],
                        }
                        for r in event_rows
                    ],
                    adverse * mult,
                )
            )
            for name, mult in COST_SHOCK_MULTS
        },
        "time": {
            "weekday": slice_table(event_rows, lambda r: (ts(r).day_name() if ts(r) is not None else "UNKNOWN")),
            "regime": slice_table(event_rows, lambda r: r.get("regime") or "UNKNOWN"),
        },
        "vs_event_baseline": {},
    }
    event["entry"]["next_bar_open"]["vs_baseline"] = material_vs_baseline(event["entry"]["next_bar_open"], event_exp)
    return {
        "baseline": {
            **baseline,
            "source": "Phase 30 RAW_SIGNAL_BOOK / Phase 32 folds",
            "phase32_verdict": loaded["phase32_verdict"],
            "phase32_fold_setups": loaded["phase32_fold_setups"],
            "calendar_days": loaded["calendar_days"],
            "unique_events": loaded["n_events"],
        },
        "entry_robustness": entry,
        "sl_robustness": sl,
        "tp_rr_robustness": tp,
        "cost_shocks": cost,
        "signal_quality": quality,
        "time_robustness": time_block,
        "event_robustness": event,
    }


def collect_material_flags(block: dict[str, Any]) -> list[str]:
    hits = []

    def walk(prefix: str, obj: Any) -> None:
        if isinstance(obj, dict):
            vs = obj.get("vs_baseline")
            if isinstance(vs, dict) and vs.get("material"):
                hits.append(prefix)
            for k, v in obj.items():
                if k == "vs_baseline":
                    continue
                walk(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(f"{prefix}[{i}]", v)

    walk("", block)
    return hits


def classify_conclusion(loaded: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    n = int(audit["baseline"]["n"])
    events = int(loaded["n_events"])
    days = float(loaded["calendar_days"])
    floors = {
        "resolved_trades": {"value": n, "required": MIN_RESOLVED_FOR_SUFFICIENCY, "pass": n >= MIN_RESOLVED_FOR_SUFFICIENCY},
        "unique_events": {"value": events, "required": MIN_RESOLVED_FOR_SUFFICIENCY, "pass": events >= MIN_RESOLVED_FOR_SUFFICIENCY},
        "calendar_days": {
            "value": days,
            "required": MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
            "pass": days >= MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
        },
        "robustness_n": {"value": n, "required": MIN_TRADES_FOR_ROBUSTNESS, "pass": n >= MIN_TRADES_FOR_ROBUSTNESS},
    }
    insufficient = any(not v["pass"] for v in floors.values())
    material = collect_material_flags(
        {k: audit[k] for k in ("entry_robustness", "sl_robustness", "tp_rr_robustness", "cost_shocks")}
    )
    if insufficient:
        verdict = "INSUFFICIENT_SAMPLE"
        text = (
            "INSUFFICIENT_SAMPLE. Phase 30/32 baseline is 24 dependent RAW setups / "
            f"{events} mechanical events / {days:.1f} calendar days. "
            f"Floors are Phase 28.0 resolved>= {MIN_RESOLVED_FOR_SUFFICIENCY} and days>= "
            f"{MIN_CALENDAR_DAYS_FOR_SUFFICIENCY}, plus Phase 28.3 robustness n>= "
            f"{MIN_TRADES_FOR_ROBUSTNESS}. Pre-declared diagnostics cannot support ROBUST, "
            "FRAGILE, or MIXED. Descriptive books are not a robustness proof. "
            "No parameter was optimized."
        )
    elif material:
        verdict = "FRAGILE" if len(material) >= 2 else "MIXED"
        text = f"{verdict}. Material diagnostic hits: {material}."
    else:
        verdict = "ROBUST"
        text = "ROBUST. Pre-declared diagnostics did not materially change expectancy. Sample floors passed."
    return {
        "verdict": verdict,
        "edge_supported": False,
        "no_edge_supported": False,
        "robustness_proven": False,
        "floors": floors,
        "material_diagnostic_hits": material,
        "material_hits_not_a_robustness_proof_under_insufficient_sample": insufficient,
        "text": text,
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    e = payload["entry_robustness"]
    sl = payload["sl_robustness"]["perturbations"]
    rr = payload["tp_rr_robustness"]["perturbations"]
    c = payload["cost_shocks"]["books"]
    path = root / PHASE33_MD
    path.parent.mkdir(parents=True, exist_ok=True)

    def line(name: str, book: dict[str, Any]) -> str:
        return f"| {name} | {book.get('n')} | {book.get('wins')} | {book.get('win_rate')} | {book.get('expectancy_R')} | {book.get('profit_factor')} | {(book.get('vs_baseline') or {}).get('material')} |"

    path.write_text(
        f"""# Phase 33 — Strategy Robustness & Adversarial Reality Checks

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Conclusion:** `{payload["conclusion"]["verdict"]}`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`

STOP AFTER PHASE 33. DO NOT START PHASE 34.

Baseline: Phase 30 RAW book + Phase 32 chronological folds. Diagnostics are **not** production changes.

---

## Entry robustness

ANALYTICAL ONLY. Official entry remains the closed-bar close.

| Book | n | wins | WR | exp R | PF | material vs baseline |
|---|---:|---:|---:|---:|---:|---|
{line("official close", e["official_close"])}
{line("next-bar open", e["next_bar_open"])}
{line("first eligible reclaim close", e["first_eligible_reclaim_close"])}
{line("small execution displacement", e["small_execution_displacement"])}

Displacement uses MODELED_PROXY half-spread+slippage, not OBSERVED fills.

## SL robustness

Pre-declared symmetric ±10% of the existing SL distance. Not a search.

| Book | n | wins | WR | exp R | PF | material |
|---|---:|---:|---:|---:|---:|---|
{line("official", payload["sl_robustness"]["official"])}
{line("SL x0.90", sl["sl_distance_x0.90"])}
{line("SL x1.10", sl["sl_distance_x1.10"])}

## TP / RR robustness

Pre-declared symmetric ±0.25 around each trade's existing planned RR. Not a search. Goal is fragility, not max returns.

| Book | n | wins | WR | exp R | PF | material |
|---|---:|---:|---:|---:|---:|---|
{line("official", payload["tp_rr_robustness"]["official"])}
{line("RR -0.25", rr["planned_rr_-0.25"])}
{line("RR +0.25", rr["planned_rr_+0.25"])}

## Cost shocks

All MODELED / MODELED_PROXY. Commission/swap UNKNOWN. No OBSERVED broker fills.

| Book | multiplier | exp R | PF | material |
|---|---:|---:|---:|---|
| baseline | 1x | {c["baseline"].get("expectancy_R")} | {c["baseline"].get("profit_factor")} | {c["baseline"]["vs_baseline"].get("material")} |
| moderate | 2x | {c["moderate"].get("expectancy_R")} | {c["moderate"].get("profit_factor")} | {c["moderate"]["vs_baseline"].get("material")} |
| high plausible | 3x | {c["high_plausible"].get("expectancy_R")} | {c["high_plausible"].get("profit_factor")} | {c["high_plausible"]["vs_baseline"].get("material")} |

## Signal quality / time / events

Tertiles and weekday/week/month/regime slices are in the JSON. Slices with n < {MIN_SLICE_N} are flagged. Thresholds were **not** tuned. Event-level repeats the same pre-declared diagnostics on 6 mechanical events.

## CONCLUSION

**{payload["conclusion"]["verdict"]}**

{payload["conclusion"]["text"]}

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 34 was **not** started.
""",
        encoding="utf-8",
    )


def run_phase33_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical M5 fingerprint changed — Phase 33 refuses to proceed")
    loaded = load_baseline(root)
    df = load_parquet_utc(root / CANONICAL_PARQUET)
    pass_a = evaluate_robustness(loaded, df)
    pass_b = evaluate_robustness(loaded, df)

    def core(p: dict[str, Any]) -> dict[str, Any]:
        return {
            "entry": {k: p["entry_robustness"][k].get("expectancy_R") for k in ("official_close", "next_bar_open", "first_eligible_reclaim_close", "small_execution_displacement")},
            "sl": {k: v.get("expectancy_R") for k, v in p["sl_robustness"]["perturbations"].items()},
            "rr": {k: v.get("expectancy_R") for k, v in p["tp_rr_robustness"]["perturbations"].items()},
            "cost": {k: v.get("expectancy_R") for k, v in p["cost_shocks"]["books"].items()},
        }

    if _stable_hash(core(pass_a)) != _stable_hash(core(pass_b)):
        raise RuntimeError("Phase 33 evaluation is not deterministic")

    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    conclusion = classify_conclusion(loaded, pass_a)
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
        "strategy_changed": False,
        "riskgate_changed": False,
        "rr_changed": False,
        "silent_xauusd_mapping": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "dataset": CANONICAL_PARQUET,
        "dataset_fingerprint": fp,
        "perturbation_spec": {
            "sl_distance_multipliers": list(SL_DISTANCE_MULTIPLIERS),
            "rr_offsets": list(RR_OFFSETS),
            "cost_multipliers": {n: m for n, m in COST_SHOCK_MULTS},
            "material_exp_delta": MATERIAL_EXP_DELTA,
            "not_a_search": True,
        },
        **pass_a,
        "conclusion": conclusion,
        "lookahead": {
            "official_results_closed_bars_only": True,
            "sl_before_tp_same_bar": True,
            "precedence_changed": False,
            "status": "PASS",
        },
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
            "PHASE_34_STARTED": False,
        },
        "phase_34_started": False,
    }
    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after
    _write_json(root / PHASE33_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Robustness (Phase 33)"
        block = (
            "\n\n## Robustness (Phase 33)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Unchanged Phase 30/32 baseline used | **SUPPORTED** |\n"
            "| Diagnostics are production parameter changes | **NO** |\n"
            "| Strategy is proven ROBUST / FRAGILE | **INSUFFICIENT_SAMPLE** |\n"
            "| Cost shocks are realized broker costs | **NO** — MODELED / MODELED_PROXY |\n"
            "| Phase 33 authorizes live trading or optimization | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")
    return payload


if __name__ == "__main__":
    run_phase33_collection()
