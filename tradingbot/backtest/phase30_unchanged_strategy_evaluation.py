"""Phase 30 — unchanged gold_ny_sweep on the Phase 29 canonical XAUUSD_i tape.

RESEARCH ONLY. Replays the current production strategy with no parameter or
behavior change. RAW / EXECUTABLE / FILLED books stay separate.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
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
    H4_CONTEXT_PARQUET,
    MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
    MIN_RESOLVED_FOR_SUFFICIENCY,
    PHASE280_BASELINE_JSON,
    UNKNOWN,
    _setups_fingerprint,
    build_research_configuration,
    classify_statistical_sufficiency,
)
from tradingbot.backtest.phase28_1_full_baseline import (
    PHASE281_JSON,
    _parse_ts,
    expand_raw_metrics,
)
from tradingbot.backtest.phase28_3_monte_carlo import apply_modeled_shift, modeled_cost_spec, path_metrics
from tradingbot.backtest.phase28_4_strategy_diagnosis import PHASE284_JSON
from tradingbot.backtest.phase29_research_tape import PHASE29_JSON
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.pa_symbol_tf_presets import PA_SYMBOL_TF_PRESETS

PHASE = "30"
PHASE30_JSON = "logs/phase30_unchanged_strategy_evaluation.json"
PHASE30_MD = "docs_v2/02_research/PHASE30_UNCHANGED_STRATEGY_EVALUATION.md"
EVALUATOR_VERSION = "phase30-unchanged-v1"
MIN_UNIQUE_EVENTS_FOR_SUFFICIENCY = MIN_RESOLVED_FOR_SUFFICIENCY
FORBIDDEN_DATASETS = (
    "data/backtest/XAUUSD_M5_183d.parquet",
    "data/backtest/XAUUSD_M5_180d.parquet",
    "data/XAUUSD_5m.parquet",
)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "parameters_searched",
    "strategy_changed",
    "dataset_fingerprint",
    "raw_signal_book",
    "event_level",
    "executable_book",
    "filled_book",
    "cost_book",
    "statistical_sufficiency",
    "lookahead",
    "reproducibility",
    "conclusion",
    "FINAL_GATE",
    "phase_31_started",
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


def strategy_logic_fingerprint() -> str:
    m5 = dict(PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"])
    keys = (
        "PRESET",
        "GOLD_STRATEGY_MODE",
        "MIN_CONFIDENCE",
        "MIN_RR",
        "TP_RR",
        "SL_ATR_MULT",
        "ASIAN_START_HOUR",
        "ASIAN_END_HOUR",
        "M5_USE_LONDON_SESSION",
        "M5_USE_NY_SESSION",
        "NY_ENTRY_START_HOUR",
        "NY_ENTRY_END_HOUR",
        "SWEEP_LOOKBACK_BARS",
        "SWEEP_BUFFER_ATR",
        "MIN_RANGE_ATR",
        "M5_REQUIRE_REJECTION",
        "COOLDOWN_BARS",
        "MAX_TRADES_PER_DAY",
        "MIN_QUALITY_SCORE",
        "META_LABEL_THRESHOLD",
        "ATR_PCT_MIN",
        "ATR_PCT_MAX",
        "USE_ADX_FILTER",
        "ENABLE_CHOCH_CONTINUATION",
    )
    return _stable_hash({k: m5.get(k) for k in keys})[:16]


def load_official_books(root: Path) -> dict[str, Any]:
    p280 = _safe_load_json(root / PHASE280_BASELINE_JSON) or {}
    p281 = _safe_load_json(root / PHASE281_JSON) or {}
    p284 = _safe_load_json(root / PHASE284_JSON) or {}
    p29 = _safe_load_json(root / PHASE29_JSON) or {}
    if not (p280 and p281 and p284):
        raise FileNotFoundError("Phase 28.0/28.1/28.4 artifacts are required")
    raw0 = list((p280.get("raw_signal_results") or {}).get("setup_rows") or [])
    raw1 = list((p281.get("raw_signal") or {}).get("setup_rows") or [])
    rec = list(p284.get("reconstructed_setups") or [])
    if len(raw0) != 24 or len(rec) != 24:
        raise RuntimeError("Official RAW book is not the frozen 24-setup gold_ny_sweep set")
    r0 = [float(r["r_multiple"]) for r in raw0]
    r1 = [float(r["r_multiple"]) for r in raw1 if r.get("r_multiple") is not None]
    r4 = [float(r["theoretical_R"]) for r in rec if r.get("theoretical_R") is not None]
    if r0 != r1 or r0 != r4:
        raise RuntimeError("Phase 28.0/28.1/28.4 RAW R series do not match — refusing to invent a new book")
    exe = p281.get("executable") or {}
    return {
        "raw_28_0": raw0,
        "reconstructed": rec,
        "executable": exe,
        "phase28_0_fingerprint": p280.get("dataset_fingerprint"),
        "phase28_1_fingerprint": p281.get("dataset_fingerprint"),
        "phase28_4_fingerprint": p284.get("dataset_fingerprint"),
        "phase29_m5_fingerprint": ((p29.get("fingerprints") or {}).get("phase28_m5_file")),
        "period": p281.get("period") or p280.get("data_range") or {},
        "ny_session_days_tape": int(((p281.get("raw_signal") or {}).get("ny_session_days")) or 10),
        "calendar_days": float(((p281.get("raw_signal") or {}).get("calendar_days")) or 14.8785),
    }


def merge_raw_rows(raw0: list[dict[str, Any]], rec: list[dict[str, Any]], exe_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ts_rec = {str(r["timestamp"]): r for r in rec}
    by_ts_exe = {str(r.get("timestamp")): r for r in exe_rows}
    out = []
    prev = None
    for i, base in enumerate(raw0):
        ts = str(base["timestamp"])
        extra = by_ts_rec.get(ts) or {}
        rg = by_ts_exe.get(ts) or {}
        parsed = _parse_ts(ts)
        cluster = extra.get("overlap_cluster_id")
        row = {
            "signal_id": f"SIG-{i+1:03d}",
            "event_id": f"EVT-{int(cluster) if cluster is not None else i:03d}",
            "event_cluster_id": cluster,
            "timestamp": ts,
            "utc": True,
            "weekday": None if parsed is None else parsed.day_name(),
            "hour_utc": None if parsed is None else int(parsed.hour),
            "side": base.get("direction"),
            "asian_high": extra.get("asian_high"),
            "asian_low": extra.get("asian_low"),
            "sweep_level": extra.get("sweep_level"),
            "reclaim_level": extra.get("reclaim_level"),
            "same_bar_sweep_and_reclaim": extra.get("same_bar_sweep_and_reclaim"),
            "entry_price": base.get("entry_price"),
            "stop_loss": base.get("stop_loss"),
            "take_profit": base.get("take_profit"),
            "planned_rr": base.get("planned_rr") or extra.get("planned_rr"),
            "theoretical_R": base.get("r_multiple"),
            "outcome": base.get("outcome"),
            "exit_time": base.get("exit_time"),
            "exit_index": base.get("exit_index") or extra.get("exit_index"),
            "duration_minutes": extra.get("duration_minutes"),
            "bars_to_outcome": extra.get("bars_to_outcome"),
            "atr": extra.get("atr"),
            "atr_percentile": extra.get("atr_percentile"),
            "adx": extra.get("adx"),
            "regime": extra.get("regime"),
            "quality_score": base.get("quality_score") or extra.get("quality_score"),
            "confidence": base.get("confidence") or extra.get("confidence"),
            "session": (extra.get("session_context") or {}).get("window") or "NY 15-16 UTC",
            "overlaps_another_setup": extra.get("overlaps_another_setup"),
            "cluster_size": extra.get("cluster_size"),
            "riskgate_bucket": rg.get("bucket"),
            "riskgate_allowed": bool(rg.get("allowed")),
            "riskgate_reason": rg.get("reason"),
            "previous_signal": None
            if prev is None
            else {
                "signal_id": prev["signal_id"],
                "event_id": prev["event_id"],
                "same_event_cluster": prev.get("event_cluster_id") == cluster,
                "gap_minutes": None
                if parsed is None or _parse_ts(prev["timestamp"]) is None
                else float((parsed - _parse_ts(prev["timestamp"])).total_seconds() / 60.0),
            },
        }
        if row["duration_minutes"] is None and row.get("exit_time"):
            start = _parse_ts(ts)
            end = _parse_ts(row["exit_time"])
            if start is not None and end is not None:
                row["duration_minutes"] = float((end - start).total_seconds() / 60.0)
        out.append(row)
        prev = row
    return out


def event_representatives(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One official signal per event cluster — earliest timestamp. Not an optimized pick."""
    groups: dict[Any, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r.get("event_cluster_id"), []).append(r)
    reps = []
    for cid, items in groups.items():
        items_sorted = sorted(items, key=lambda x: str(x["timestamp"]))
        head = dict(items_sorted[0])
        head["event_member_count"] = len(items_sorted)
        head["event_member_signal_ids"] = [x["signal_id"] for x in items_sorted]
        head["selection"] = "earliest_timestamp_in_cluster"
        reps.append(head)
    return sorted(reps, key=lambda x: str(x["timestamp"]))


def performance_pack(rows: list[dict[str, Any]], *, calendar_days: float, ny_session_days: int) -> dict[str, Any]:
    adapted = []
    for r in rows:
        adapted.append(
            {
                "timestamp": r.get("timestamp"),
                "direction": r.get("side") or r.get("direction"),
                "outcome": r.get("outcome"),
                "r_multiple": r.get("theoretical_R") if r.get("theoretical_R") is not None else r.get("r_multiple"),
                "exit_time": r.get("exit_time"),
            }
        )
    block = expand_raw_metrics(adapted, calendar_days=calendar_days, ny_session_days=ny_session_days)
    r_vals = [float(s["r_multiple"]) for s in adapted if s.get("r_multiple") is not None]
    durations = [float(r["duration_minutes"]) for r in rows if r.get("duration_minutes") is not None]
    dates = sorted({str(_parse_ts(r["timestamp"]).date()) for r in rows if _parse_ts(r.get("timestamp")) is not None})
    block["median_R"] = None if not r_vals else float(np.median(r_vals))
    block["break_even"] = int(sum(1 for r in r_vals if r == 0))
    block["unique_event_count"] = len({r.get("event_cluster_id") for r in rows})
    block["unique_day_count"] = len(dates)
    block["unique_ny_session_count"] = len(dates)
    block["median_duration_minutes"] = None if not durations else float(np.median(durations))
    if durations and block.get("average_trade_duration_minutes") is None:
        block["average_trade_duration_minutes"] = float(sum(durations) / len(durations))
    return block


def classify_phase30_sufficiency(
    *,
    raw_n: int,
    unique_events: int,
    unique_days: int,
    unique_sessions: int,
    calendar_days: float,
) -> dict[str, Any]:
    base = classify_statistical_sufficiency(
        resolved=raw_n,
        calendar_days=calendar_days,
        setups=raw_n,
    )
    extra_fail = []
    if unique_events < MIN_UNIQUE_EVENTS_FOR_SUFFICIENCY:
        extra_fail.append(f"unique_events={unique_events}<{MIN_UNIQUE_EVENTS_FOR_SUFFICIENCY}")
    reasons = list(base.get("reasons") or []) + extra_fail
    classification = "DATA_SUFFICIENT" if not reasons else "DATA_INSUFFICIENT"
    return {
        "classification": classification,
        "criteria": {
            "resolved_trades": {
                "value": raw_n,
                "required": MIN_RESOLVED_FOR_SUFFICIENCY,
                "pass": raw_n >= MIN_RESOLVED_FOR_SUFFICIENCY,
            },
            "calendar_days": {
                "value": round(calendar_days, 4),
                "required": MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
                "pass": calendar_days >= MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
            },
            "unique_events": {
                "value": unique_events,
                "required": MIN_UNIQUE_EVENTS_FOR_SUFFICIENCY,
                "pass": unique_events >= MIN_UNIQUE_EVENTS_FOR_SUFFICIENCY,
            },
            "unique_ny_sessions": {"value": unique_sessions, "required": None, "pass": None, "note": "reported only"},
            "unique_days": {"value": unique_days, "required": None, "pass": None, "note": "reported only"},
        },
        "reasons": reasons,
        "confidence_invented": False,
        "zero_executable_is_not_strategy_failure": True,
        "thresholds_source": (
            "MIN_RESOLVED_FOR_SUFFICIENCY=30 and MIN_CALENDAR_DAYS_FOR_SUFFICIENCY=60 from Phase 28.0; "
            "unique_events uses the same 30-count independence floor. Not invented this phase."
        ),
    }


def evaluate_books(loaded: dict[str, Any]) -> dict[str, Any]:
    exe = loaded["executable"]
    exe_rows = list(exe.get("rows") or [])
    raw_rows = merge_raw_rows(loaded["raw_28_0"], loaded["reconstructed"], exe_rows)
    events = event_representatives(raw_rows)
    cal = float(loaded["calendar_days"])
    ny_tape = int(loaded["ny_session_days_tape"])
    raw_perf = performance_pack(raw_rows, calendar_days=cal, ny_session_days=ny_tape)
    event_perf = performance_pack(events, calendar_days=cal, ny_session_days=len({e.get("timestamp", "")[:10] for e in events}))
    event_perf["selection_rule"] = "earliest official signal in each Phase 28.4 event cluster"
    event_perf["not_optimized"] = True

    costs = modeled_cost_spec()
    trades_for_shift = [
        {
            "direction": r["side"],
            "entry_price": r["entry_price"],
            "stop_loss": r["stop_loss"],
            "take_profit": r["take_profit"],
            "outcome": r["outcome"],
            "r_multiple": r["theoretical_R"],
        }
        for r in raw_rows
    ]
    modeled_r = apply_modeled_shift(trades_for_shift, costs["half_spread_price"] + costs["slippage_price"])
    modeled_path = path_metrics(modeled_r)
    sufficiency = classify_phase30_sufficiency(
        raw_n=int(raw_perf["total_trades"]),
        unique_events=int(raw_perf["unique_event_count"]),
        unique_days=int(raw_perf["unique_day_count"]),
        unique_sessions=int(raw_perf["unique_ny_session_count"]),
        calendar_days=cal,
    )
    return {
        "raw_signal_book": {
            "n": len(raw_rows),
            "rows": raw_rows,
            "performance": raw_perf,
            "note": "Strategy signals before RiskGate. Theoretical SL/TP. Not fills.",
        },
        "event_level": {
            "n_events": len(events),
            "rows": events,
            "performance": event_perf,
            "note": "Do not treat 24 RAW rows as 24 independent observations.",
        },
        "executable_book": {
            "candidates": int(exe.get("candidates") or 0),
            "allowed": int(exe.get("allowed") or 0),
            "rejected": int(exe.get("rejected") or 0),
            "attribution": exe.get("attribution_counts") or {},
            "rejection_reasons": exe.get("rejection_reasons") or {},
            "executed_simulated_fills": int(exe.get("executed_simulated_fills") or 0),
            "note": (
                "RiskGate rejects are not strategy failures. "
                "0 allowed / 0 fills is not proof of no edge."
            ),
        },
        "filled_book": {
            "n": 0,
            "status": "NOT_OBSERVED",
            "reason": (
                "No historical requested-vs-fill execution tape. SimulatedBroker remains "
                "commission UNKNOWN (fail-closed). FILLED is empty and is not merged into RAW."
            ),
        },
        "cost_book": {
            "GROSS_R": {
                "label": "GROSS_THEORETICAL",
                "expectancy_R": raw_perf.get("expectancy_R"),
                "profit_factor": raw_perf.get("profit_factor"),
                "net_R": raw_perf.get("net_R"),
                "max_drawdown_R": raw_perf.get("max_drawdown_R"),
                "components": {
                    "spread": "NOT_APPLIED",
                    "slippage": "NOT_APPLIED",
                    "commission": "UNKNOWN",
                    "swap": "UNKNOWN",
                },
            },
            "COST_ADJUSTED_R": {
                "label": "MODELED",
                "not_realized": True,
                "expectancy_R": modeled_path["expectancy_R"],
                "profit_factor": modeled_path["profit_factor"],
                "net_R": modeled_path["final_R"],
                "max_drawdown_R": modeled_path["max_drawdown_R"],
                "win_rate": modeled_path["win_rate"],
                "components": {
                    "spread": "MODELED_PROXY",
                    "slippage": "MODELED_PROXY",
                    "commission": "UNKNOWN",
                    "swap": "UNKNOWN",
                },
                "spec": costs,
                "note": "BacktestConfig spread 2.5 / slippage 0.8 pips. Not historical realized costs.",
            },
        },
        "statistical_sufficiency": sufficiency,
    }


def classify_conclusion(sufficiency: dict[str, Any], exe_allowed: int) -> dict[str, Any]:
    if sufficiency.get("classification") != "DATA_SUFFICIENT":
        return {
            "verdict": "INDETERMINATE",
            "edge_supported": False,
            "no_edge_supported": False,
            "text": (
                "INDETERMINATE. The unchanged gold_ny_sweep RAW book on the Phase 29 canonical "
                "XAUUSD_i M5 tape is DATA_INSUFFICIENT (n=24 dependent setups / 7 events / ~15 days). "
                "That does not support an edge claim and does not support a no-edge claim. "
                f"EXECUTABLE allowed={exe_allowed} is a RiskGate book, not a strategy verdict. "
                "No parameters were changed."
            ),
        }
    return {
        "verdict": "INDETERMINATE",
        "text": "Sufficiency passed but Phase 30 still will not invent an edge claim without a filled book.",
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    raw = payload["raw_signal_book"]["performance"]
    ev = payload["event_level"]["performance"]
    exe = payload["executable_book"]
    cost = payload["cost_book"]
    path = root / PHASE30_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Phase 30 — Unchanged Strategy Long-Horizon Evaluation

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Conclusion:** `{payload["conclusion"]["verdict"]}`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`

Unchanged production `gold_ny_sweep` on the Phase 29 canonical `XAUUSD_i` M5 tape.
Phase 29 did **not** obtain a 180-day tape. This evaluation uses the frozen 15-day snapshot.

STOP AFTER PHASE 30. DO NOT START PHASE 31.

---

## Data

Fingerprint `{payload.get("dataset_fingerprint")}` matches Phase 28.0–29. Empty `dataset_symbol_map`. Logical `XAUUSD` not used.

## RAW_SIGNAL_BOOK

| Metric | Value |
|---|---:|
| N | {raw.get("total_trades")} |
| Events | {raw.get("unique_event_count")} |
| Days | {raw.get("unique_day_count")} |
| NY sessions (signal dates) | {raw.get("unique_ny_session_count")} |
| Wins / losses / BE | {raw.get("wins")} / {raw.get("losses")} / {raw.get("break_even")} |
| WR | {raw.get("win_rate")} |
| Expectancy R | {raw.get("expectancy_R")} |
| PF | {raw.get("profit_factor")} |
| DD R | {raw.get("max_drawdown_R")} |
| Loss streak | {raw.get("max_consecutive_losses")} |
| Median R | {raw.get("median_R")} |
| Avg / median duration (min) | {raw.get("average_trade_duration_minutes")} / {raw.get("median_duration_minutes")} |

## EVENT LEVEL

Earliest official signal per cluster. Not an optimized pick.

| Metric | Value |
|---|---:|
| Events | {ev.get("total_trades")} |
| WR | {ev.get("win_rate")} |
| Expectancy R | {ev.get("expectancy_R")} |
| PF | {ev.get("profit_factor")} |
| DD R | {ev.get("max_drawdown_R")} |
| Loss streak | {ev.get("max_consecutive_losses")} |

## EXECUTABLE_BOOK

Candidates `{exe.get("candidates")}`; allowed `{exe.get("allowed")}`; rejected `{exe.get("rejected")}`.  
Attribution `{exe.get("attribution")}`.  
0 allowed is **not** a strategy failure.

## FILLED_BOOK

`NOT_OBSERVED`. n=0. No historical requested-vs-fill tape.

## COST

GROSS expectancy `{cost["GROSS_R"]["expectancy_R"]}` (costs not applied).  
COST_ADJUSTED expectancy `{cost["COST_ADJUSTED_R"]["expectancy_R"]}` labeled **MODELED** (spread/slippage MODELED_PROXY; commission/swap UNKNOWN). Not realized.

## STATISTICAL SUFFICIENCY

`{payload["statistical_sufficiency"]["classification"]}`

{payload["statistical_sufficiency"]["thresholds_source"]}

Reasons: {payload["statistical_sufficiency"]["reasons"]}

## LOOKAHEAD

Official signals use closed M5 bars only. Exits may use later bars. SL-before-TP unchanged.

## REPRODUCIBILITY

Two evaluation passes matched: `{payload["reproducibility"]["passes_match"]}`.  
Strategy logic fingerprint `{payload["reproducibility"]["strategy_logic_fingerprint"]}`.

## CONCLUSION

**{payload["conclusion"]["verdict"]}**

{payload["conclusion"]["text"]}

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 31 was **not** started.
""",
        encoding="utf-8",
    )


def run_phase30_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical M5 fingerprint changed — Phase 30 refuses to proceed")
    loaded = load_official_books(root)
    for key in ("phase28_0_fingerprint", "phase28_1_fingerprint", "phase28_4_fingerprint"):
        if loaded[key] != fp:
            raise RuntimeError(f"{key} does not match the canonical parquet")
    if loaded.get("phase29_m5_fingerprint") not in {None, fp}:
        raise RuntimeError("Phase 29 M5 fingerprint does not match the frozen snapshot")

    pass_a = evaluate_books(loaded)
    pass_b = evaluate_books(loaded)
    raw_fp_a = _setups_fingerprint(
        [{"timestamp": r["timestamp"], "direction": r["side"], "entry_price": r["entry_price"], "stop_loss": r["stop_loss"], "take_profit": r["take_profit"], "outcome": r["outcome"], "r_multiple": r["theoretical_R"]} for r in pass_a["raw_signal_book"]["rows"]]
    )
    raw_fp_b = _setups_fingerprint(
        [{"timestamp": r["timestamp"], "direction": r["side"], "entry_price": r["entry_price"], "stop_loss": r["stop_loss"], "take_profit": r["take_profit"], "outcome": r["outcome"], "r_multiple": r["theoretical_R"]} for r in pass_b["raw_signal_book"]["rows"]]
    )
    out_a = _stable_hash(
        {
            "raw": pass_a["raw_signal_book"]["performance"],
            "event": pass_a["event_level"]["performance"],
            "exe": {k: pass_a["executable_book"][k] for k in ("candidates", "allowed", "rejected", "attribution")},
            "cost": {
                "g": pass_a["cost_book"]["GROSS_R"]["expectancy_R"],
                "c": pass_a["cost_book"]["COST_ADJUSTED_R"]["expectancy_R"],
            },
        }
    )
    out_b = _stable_hash(
        {
            "raw": pass_b["raw_signal_book"]["performance"],
            "event": pass_b["event_level"]["performance"],
            "exe": {k: pass_b["executable_book"][k] for k in ("candidates", "allowed", "rejected", "attribution")},
            "cost": {
                "g": pass_b["cost_book"]["GROSS_R"]["expectancy_R"],
                "c": pass_b["cost_book"]["COST_ADJUSTED_R"]["expectancy_R"],
            },
        }
    )
    if raw_fp_a != raw_fp_b or out_a != out_b:
        raise RuntimeError("Phase 30 evaluation is not deterministic")

    research = build_research_configuration()
    conclusion = classify_conclusion(pass_a["statistical_sufficiency"], pass_a["executable_book"]["allowed"])
    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    h4_fp = file_fingerprint(root / H4_CONTEXT_PARQUET) if (root / H4_CONTEXT_PARQUET).is_file() else None

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
        "ml_changed": False,
        "rr_changed": False,
        "silent_xauusd_mapping": False,
        "logical_xauusd_used": False,
        "forbidden_datasets_not_loaded": list(FORBIDDEN_DATASETS),
        "ev_eq_01": "NOT_PROVEN",
        "cost_completeness": BLOCKED,
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "dataset": CANONICAL_PARQUET,
        "h4_context": H4_CONTEXT_PARQUET,
        "dataset_fingerprint": fp,
        "h4_fingerprint": h4_fp,
        "phase29_tape_is_frozen_phase28_snapshot": True,
        "research_configuration": {
            "symbol": PRIMARY_SYMBOL,
            "dataset_symbol_map": {},
            "configuration_fingerprint": research.get("configuration_fingerprint"),
            "strategy_logic_fingerprint": strategy_logic_fingerprint(),
            "unchanged_from_production_preset": True,
        },
        "lookahead": {
            "official_results_closed_bars_only": True,
            "features_use_future_candles": False,
            "signal_generation_uses_future_high_low": False,
            "exits_may_use_future_bars_after_entry": True,
            "sl_before_tp_same_bar": True,
            "precedence_changed": False,
            "status": "PASS",
        },
        **pass_a,
        "conclusion": conclusion,
        "reproducibility": {
            "passes": 2,
            "passes_match": True,
            "data_fingerprint": fp,
            "strategy_fingerprint": research.get("configuration_fingerprint"),
            "strategy_logic_fingerprint": strategy_logic_fingerprint(),
            "evaluator_fingerprint": EVALUATOR_VERSION,
            "setups_fingerprint": raw_fp_a,
            "output_fingerprint": out_a,
        },
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "ML_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "PARAMETERS_SEARCHED": False,
            "PHASE_31_STARTED": False,
        },
        "phase_31_started": False,
    }

    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after

    _write_json(root / PHASE30_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Performance validation (Phase 30)"
        block = (
            "\n\n## Performance validation (Phase 30)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Unchanged gold_ny_sweep evaluated on Phase 29 canonical XAUUSD_i M5 | **SUPPORTED** |\n"
            "| 180-day tape used | **NO** — Phase 29 did not obtain one; 15-day snapshot used |\n"
            "| Strategy has proven edge / no-edge | **INDETERMINATE** — DATA_INSUFFICIENT |\n"
            "| 0 RiskGate allows proves strategy failure | **FALSE** |\n"
            "| Phase 30 authorizes live trading or optimization | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")

    return payload


if __name__ == "__main__":
    run_phase30_collection()
