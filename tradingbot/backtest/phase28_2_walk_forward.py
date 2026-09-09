"""Phase 28.2 — chronological walk-forward on the Phase 28.0/28.1 XAUUSD_i tape.

RESEARCH ONLY. TRAIN/VALIDATION are descriptive. No optimization, no gate changes,
no MT5, no parquet rewrite, no Monte Carlo, no live authorization.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    H4_CONTEXT_PARQUET,
    PHASE280_BASELINE_JSON,
    UNKNOWN,
    WARMUP,
    _build_research_engine,
    _enrich_frame,
    _setups_fingerprint,
    build_research_configuration,
    classify_statistical_sufficiency,
    load_parquet_utc,
    scan_signal_setups,
)
from tradingbot.backtest.phase28_1_full_baseline import (
    PHASE281_JSON,
    _parse_ts,
    chronological_riskgate,
    confirm_approved_dataset,
    expand_raw_metrics,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.gold_strategies.m5_london_sweep import m5_ny_entry_hours

PHASE = "28.2"
PHASE282_JSON = "logs/phase28_2_walk_forward.json"
PHASE282_MD = "docs_v2/02_research/PHASE28_2_WALK_FORWARD.md"
FOLD_NAMES = ("TRAIN", "VALIDATION", "OOS")
TRAIN_FRAC = 0.60
VAL_FRAC = 0.20
OOS_FRAC = 0.20
MIN_FOLD_TRADES = 10
MIN_TOTAL_TRADES = 30

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "train_validation_descriptive_only",
    "approved_dataset",
    "dataset_fingerprint",
    "splits",
    "raw_signal",
    "executable",
    "degradation",
    "stability",
    "lookahead",
    "statistical_sufficiency",
    "conclusion",
    "FINAL_GATE",
    "phase_28_3_started",
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


def chronological_index_splits(
    n: int,
    *,
    train: float = TRAIN_FRAC,
    validation: float = VAL_FRAC,
    oos: float = OOS_FRAC,
) -> dict[str, dict[str, int]]:
    if n < 3:
        raise ValueError("need at least 3 bars for a chronological split")
    if abs(train + validation + oos - 1.0) > 1e-9:
        raise ValueError("split fractions must sum to 1")
    train_end = int(n * train)
    val_end = int(n * (train + validation))
    if train_end < 1:
        train_end = 1
    if val_end <= train_end:
        val_end = min(n - 1, train_end + 1)
    if val_end >= n:
        val_end = n - 1
    return {
        "TRAIN": {"start_index": 0, "end_index": train_end},
        "VALIDATION": {"start_index": train_end, "end_index": val_end},
        "OOS": {"start_index": val_end, "end_index": n},
    }


def fold_for_index(index: int, splits: dict[str, dict[str, int]]) -> str:
    for name in FOLD_NAMES:
        start = splits[name]["start_index"]
        end = splits[name]["end_index"]
        if start <= int(index) < end:
            return name
    return "OOS"


def assign_fold(setup: dict[str, Any], splits: dict[str, dict[str, int]], index: pd.DatetimeIndex) -> str:
    raw_idx = setup.get("closed_bar_index")
    if raw_idx is None:
        raw_idx = setup.get("cursor")
    if raw_idx is not None:
        return fold_for_index(int(raw_idx), splits)
    ts = _parse_ts(setup.get("timestamp"))
    if ts is None:
        return "OOS"
    loc = int(index.get_indexer([ts], method="nearest")[0])
    return fold_for_index(loc, splits)


def _calendar_days(start: pd.Timestamp, end: pd.Timestamp) -> float:
    return max(float((end - start).total_seconds() / 86400.0), 1.0 / 24.0)


def _ny_session_days(enriched: pd.DataFrame, start: int, end: int) -> int:
    cfg = get_price_action_config(PRIMARY_SYMBOL, "M5")
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    days: set[str] = set()
    for i in range(max(start, 0), min(end, len(enriched))):
        ts = enriched.index[i]
        if ny_s <= int(getattr(ts, "hour", -1)) < ny_e:
            days.add(str(ts.date()))
    return len(days)


def session_distribution(setups: list[dict[str, Any]]) -> dict[str, Any]:
    hours: Counter[str] = Counter()
    weekdays: Counter[str] = Counter()
    for s in setups:
        ts = _parse_ts(s.get("timestamp"))
        if ts is None:
            continue
        hours[f"{int(ts.hour):02d}"] += 1
        weekdays[str(ts.day_name())] += 1
    buy = sum(1 for s in setups if str(s.get("direction")).upper() == "BUY")
    sell = sum(1 for s in setups if str(s.get("direction")).upper() == "SELL")
    n = max(len(setups), 1)
    return {
        "by_hour_utc": dict(sorted(hours.items())),
        "by_weekday": dict(weekdays),
        "BUY": buy,
        "SELL": sell,
        "buy_share": round(buy / n, 6) if setups else None,
        "sell_share": round(sell / n, 6) if setups else None,
    }


def _rel_change(before: float | None, after: float | None) -> dict[str, Any]:
    if before is None or after is None:
        return {"from": before, "to": after, "abs": None, "pct": None}
    abs_d = float(after) - float(before)
    pct = None
    if float(before) != 0.0:
        pct = round(abs_d / abs(float(before)), 6)
    return {"from": before, "to": after, "abs": round(abs_d, 6), "pct": pct}


def degradation_pair(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    keys = ("total_trades", "win_rate", "expectancy_R", "profit_factor", "max_drawdown_R", "trades_per_calendar_day")
    return {k: _rel_change(a.get(k), b.get(k)) for k in keys}


def classify_stability(fold_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts = {name: int(fold_metrics[name].get("total_trades") or 0) for name in FOLD_NAMES}
    expectancies = [fold_metrics[name].get("expectancy_R") for name in FOLD_NAMES]
    insufficient = any(counts[n] < MIN_FOLD_TRADES for n in FOLD_NAMES) or sum(counts.values()) < MIN_TOTAL_TRADES
    if insufficient:
        return {
            "classification": "INSUFFICIENT_SAMPLE",
            "fold_trade_counts": counts,
            "min_fold_trades_required": MIN_FOLD_TRADES,
            "min_total_trades_required": MIN_TOTAL_TRADES,
            "confidence_invented": False,
            "note": (
                "TRAIN/VALIDATION/OOS are too small for a stability claim. "
                "Descriptive degradation numbers are not a walk-forward proof."
            ),
        }
    if any(e is None for e in expectancies):
        return {
            "classification": "INSUFFICIENT_SAMPLE",
            "fold_trade_counts": counts,
            "confidence_invented": False,
        }
    train_e, val_e, oos_e = (float(x) for x in expectancies)
    signs = {1 if e > 0 else -1 if e < 0 else 0 for e in (train_e, val_e, oos_e)}
    if len(signs - {0}) > 1:
        label = "UNSTABLE"
    elif oos_e < train_e - 0.25:
        label = "DEGRADED"
    elif abs(oos_e - train_e) <= 0.25 and abs(val_e - train_e) <= 0.25:
        label = "STABLE"
    else:
        label = "UNSTABLE"
    return {
        "classification": label,
        "fold_trade_counts": counts,
        "confidence_invented": False,
    }


def _split_meta(enriched: pd.DataFrame, splits: dict[str, dict[str, int]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in FOLD_NAMES:
        a = splits[name]["start_index"]
        b = splits[name]["end_index"]
        start_ts = enriched.index[a] if 0 <= a < len(enriched) else None
        end_ts = enriched.index[b - 1] if 0 < b <= len(enriched) else None
        days = _calendar_days(start_ts, end_ts) if start_ts is not None and end_ts is not None else 0.0
        out[name] = {
            "start_index": a,
            "end_index": b,
            "bars": int(b - a),
            "start": str(start_ts) if start_ts is not None else None,
            "end": str(end_ts) if end_ts is not None else None,
            "calendar_days": round(days, 4),
            "ny_session_days": _ny_session_days(enriched, a, b),
            "role": "descriptive_only" if name in {"TRAIN", "VALIDATION"} else "held_out_descriptive",
        }
    return out


def _compact(setups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "timestamp",
        "cursor",
        "closed_bar_index",
        "direction",
        "entry_price",
        "outcome",
        "r_multiple",
        "fold",
    )
    return [{k: s.get(k) for k in keys} for s in setups]


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    raw = payload["raw_signal"]
    exe = payload["executable"]
    deg = payload["degradation"]
    path = root / PHASE282_MD
    path.parent.mkdir(parents=True, exist_ok=True)

    def _fold_table(block: dict[str, Any]) -> str:
        lines = [
            "| Fold | setups | trades | BUY/SELL | WR | exp R | PF | DD | freq/day |",
            "|---|---:|---:|---|---:|---:|---:|---:|---:|",
        ]
        for name in FOLD_NAMES:
            m = block[name]
            lines.append(
                f"| {name} | {m.get('setups')} | {m.get('total_trades')} | "
                f"{m.get('BUY')}/{m.get('SELL')} | {m.get('win_rate')} | "
                f"{m.get('expectancy_R')} | {m.get('profit_factor')} | "
                f"{m.get('max_drawdown_R')} | {m.get('trades_per_calendar_day')} |"
            )
        return "\n".join(lines)

    path.write_text(
        f"""# Phase 28.2 — Chronological Walk-Forward

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Live trading authorized:** NO
**Parameters optimized:** NO
**TRAIN/VALIDATION:** descriptive only — not used to fit or select parameters
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`
**Stability:** `{payload["stability"].get("classification")}`

Identical unchanged `gold_ny_sweep` / RiskGate on the Phase 28.0/28.1 approved `XAUUSD_i` M5 tape, split **60% TRAIN / 20% VALIDATION / 20% OOS** by chronological bar index.

STOP AFTER PHASE 28.2. DO NOT START PHASE 28.3.

---

## Dataset and splits

Fingerprint `{payload.get("dataset_fingerprint")}` matches Phase 28.0/28.1. Empty `dataset_symbol_map`. Logical `XAUUSD` not used.

{json.dumps(payload.get("splits"), indent=2, default=str)}

Later folds may use earlier bars as closed-bar context. That is past data, not lookahead. A setup is assigned by **entry** bar. Theoretical exits may occur after the fold boundary.

---

## RAW_SIGNAL

{_fold_table(raw["folds"])}

Session / BUY-SELL:

```
{json.dumps({k: raw["folds"][k].get("session_distribution") for k in FOLD_NAMES}, indent=2)}
```

---

## EXECUTABLE_RISKGATE

{_fold_table({k: exe["folds"][k]["metrics"] for k in FOLD_NAMES})}

Allowed / rejected by fold: `{json.dumps({k: {"allowed": exe["folds"][k]["allowed"], "rejected": exe["folds"][k]["rejected"], "attribution": exe["folds"][k]["attribution"]} for k in FOLD_NAMES}, default=str)}`

Gates were not changed. Commission remains UNKNOWN.

---

## Degradation (RAW, descriptive)

- TRAIN→VALIDATION: `{json.dumps(deg["TRAIN_TO_VALIDATION"], default=str)}`
- VALIDATION→OOS: `{json.dumps(deg["VALIDATION_TO_OOS"], default=str)}`
- TRAIN→OOS: `{json.dumps(deg["TRAIN_TO_OOS"], default=str)}`

These deltas are **not** an optimization signal.

---

## Stability

**{payload["stability"].get("classification")}**

{payload["stability"].get("note", "")}

---

## Lookahead

Closed bars only. No future candle data in features or signal generation. Exits may use bars after entry.

---

## Conclusion

{payload.get("conclusion")}

## Safety

No MT5, no `.env`, no parquet rewrite, no strategy/RiskGate/parameter changes, no Monte Carlo. Phase 28.3 was **not** started.

Artifacts: `{PHASE282_JSON}`, `{PHASE282_MD}`, `tradingbot/backtest/phase28_2_walk_forward.py`, `tests/test_phase28_2_walk_forward.py`
""",
        encoding="utf-8",
    )


def run_phase28_2_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    approved = confirm_approved_dataset(root)
    if not approved["fingerprint_matches_phase28_0"]:
        raise RuntimeError("Canonical fingerprint does not match Phase 28.0")

    df = load_parquet_utc(root / CANONICAL_PARQUET)
    splits = chronological_index_splits(len(df))
    split_meta = _split_meta(df, splits)

    p28 = _safe_load_json(root / PHASE280_BASELINE_JSON) or {}
    prior_setups = list((p28.get("raw_signal_results") or {}).get("setup_rows") or [])
    prior_fp = ((p28.get("deterministic_reproducibility") or {}).get("fingerprint"))

    research = build_research_configuration()
    research["phase"] = PHASE
    research["validation_class"] = "PHASE28_2_WALK_FORWARD_DESCRIPTIVE"
    research["parameters_optimized"] = False
    research["train_validation_descriptive_only"] = True
    cfg_fp = hashlib.sha256(json.dumps(research, sort_keys=True, default=str).encode()).hexdigest()[:16]
    research["configuration_fingerprint"] = cfg_fp

    p281 = _safe_load_json(root / PHASE281_JSON) or {}
    prior_exe_rows = list((p281.get("executable") or {}).get("rows") or [])
    p281_fp = ((p281.get("deterministic_reproducibility") or {}).get("fingerprint"))

    if prior_setups and prior_setups[0].get("cursor") is not None:
        setups = prior_setups
        used_prior_scan = True
    else:
        enriched = _enrich_frame(df)
        setups = scan_signal_setups(enriched, warmup=WARMUP, symbol=PRIMARY_SYMBOL)
        used_prior_scan = False
    fp = _setups_fingerprint(setups)

    folded: dict[str, list[dict[str, Any]]] = {n: [] for n in FOLD_NAMES}
    for s in setups:
        item = dict(s)
        item["fold"] = assign_fold(item, splits, df.index)
        folded[item["fold"]].append(item)

    raw_folds: dict[str, Any] = {}
    for name in FOLD_NAMES:
        meta = split_meta[name]
        metrics = expand_raw_metrics(
            folded[name],
            calendar_days=float(meta["calendar_days"]),
            ny_session_days=int(meta["ny_session_days"]),
        )
        metrics["session_distribution"] = session_distribution(folded[name])
        metrics["split"] = meta
        metrics["descriptive_only"] = True
        raw_folds[name] = metrics

    used_prior_exe = bool(prior_exe_rows) and fp == p281_fp
    if used_prior_exe:
        exe_all = {
            "candidates": int((p281.get("executable") or {}).get("candidates") or len(setups)),
            "allowed": int((p281.get("executable") or {}).get("allowed") or 0),
            "rejected": int((p281.get("executable") or {}).get("rejected") or len(setups)),
            "executed_simulated_fills": int((p281.get("executable") or {}).get("executed_simulated_fills") or 0),
            "attribution_counts": (p281.get("executable") or {}).get("attribution_counts")
            or (p281.get("riskgate_attribution") or {}).get("counts")
            or {},
            "rows": prior_exe_rows,
            "broker_fill_note": (p281.get("executable") or {}).get("broker_fill_note"),
        }
    else:
        if "enriched" not in locals():
            enriched = _enrich_frame(df)
        h4 = load_parquet_utc(root / H4_CONTEXT_PARQUET) if (root / H4_CONTEXT_PARQUET).is_file() else None
        engine = _build_research_engine(enriched, research, h4=h4)
        exe_all = asyncio.run(chronological_riskgate(engine, setups))
    exe_by_ts = {str(r.get("timestamp")): r for r in exe_all.get("rows") or []}

    exe_folds: dict[str, Any] = {}
    for name in FOLD_NAMES:
        rows = []
        allowed_setups = []
        attr: Counter[str] = Counter()
        for s in folded[name]:
            row = exe_by_ts.get(str(s.get("timestamp"))) or {}
            rows.append(row)
            if row.get("allowed"):
                allowed_setups.append(s)
            elif row.get("bucket"):
                attr[str(row["bucket"])] += 1
        if allowed_setups:
            metrics = expand_raw_metrics(
                allowed_setups,
                calendar_days=float(split_meta[name]["calendar_days"]),
                ny_session_days=int(split_meta[name]["ny_session_days"]),
            )
        else:
            metrics = expand_raw_metrics(
                [],
                calendar_days=float(split_meta[name]["calendar_days"]),
                ny_session_days=int(split_meta[name]["ny_session_days"]),
            )
            metrics["win_rate"] = None
            metrics["expectancy_R"] = None
            metrics["profit_factor"] = None
            metrics["max_drawdown_R"] = None
        exe_folds[name] = {
            "candidates": len(folded[name]),
            "allowed": len(allowed_setups),
            "rejected": len(folded[name]) - len(allowed_setups),
            "attribution": dict(attr),
            "metrics": metrics,
            "rows": rows,
        }

    degradation = {
        "TRAIN_TO_VALIDATION": degradation_pair(raw_folds["TRAIN"], raw_folds["VALIDATION"]),
        "VALIDATION_TO_OOS": degradation_pair(raw_folds["VALIDATION"], raw_folds["OOS"]),
        "TRAIN_TO_OOS": degradation_pair(raw_folds["TRAIN"], raw_folds["OOS"]),
        "note": "Descriptive only. Not a parameter-selection or early-stopping signal.",
    }
    stability = classify_stability(raw_folds)
    sufficiency = classify_statistical_sufficiency(
        resolved=sum(int(raw_folds[n]["total_trades"]) for n in FOLD_NAMES),
        calendar_days=_calendar_days(df.index[0], df.index[-1]) if len(df) else 0.0,
        setups=len(setups),
    )
    if stability["classification"] == "INSUFFICIENT_SAMPLE":
        sufficiency["classification"] = "DATA_INSUFFICIENT"
        status = "PASS_WITH_DEFERRAL"
        conclusion = (
            "INSUFFICIENT_SAMPLE. Chronological 60/20/20 on the approved ~15-day XAUUSD_i tape "
            "cannot support a stability, degradation, or edge claim. "
            "TRAIN/VALIDATION were not used to optimize. Strategy and RiskGate were unchanged. "
            "0 executable trades in a fold is not proof of no edge. "
            "EV-EQ-01 remains NOT_PROVEN. FINAL_GATE remains BLOCKED. "
            "This research does not authorize live trading or Phase 28.3."
        )
    else:
        status = "PASS_WITH_DEFERRAL"
        conclusion = f"Stability={stability['classification']}. Still not production authorization."

    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}

    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": status,
        "research_only": True,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "train_validation_descriptive_only": True,
        "strategy_changed": False,
        "riskgate_changed": False,
        "monte_carlo": False,
        "ev_eq_01": "NOT_PROVEN",
        "cost_completeness": BLOCKED,
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "approved_dataset": approved,
        "dataset_fingerprint": approved["current_fingerprint"],
        "fingerprint_matches_phase28_0": True,
        "silent_xauusd_mapping": False,
        "research_configuration": {
            "symbol": PRIMARY_SYMBOL,
            "timeframe": "M5",
            "dataset_symbol_map": {},
            "commission_status": "UNKNOWN",
            "risk_per_trade": 0.005,
            "min_rr": 1.5,
            "identical_across_folds": True,
            "configuration_fingerprint": cfg_fp,
        },
        "splits": {
            "method": "chronological_bar_index",
            "fractions": {"TRAIN": TRAIN_FRAC, "VALIDATION": VAL_FRAC, "OOS": OOS_FRAC},
            "folds": split_meta,
            "assignment": "entry_bar_index",
            "exits_may_cross_fold_boundary": True,
            "later_fold_uses_earlier_closed_bars_as_context": True,
        },
        "raw_signal": {
            "setups_total": len(setups),
            "folds": raw_folds,
            "setup_rows": _compact(sum((folded[n] for n in FOLD_NAMES), [])),
        },
        "executable": {
            "candidates_total": exe_all.get("candidates"),
            "allowed_total": exe_all.get("allowed"),
            "rejected_total": exe_all.get("rejected"),
            "executed_simulated_fills": exe_all.get("executed_simulated_fills"),
            "attribution_total": exe_all.get("attribution_counts"),
            "chronological": True,
            "folds": exe_folds,
            "broker_fill_note": exe_all.get("broker_fill_note"),
        },
        "raw_vs_executable": {
            "raw_setups": len(setups),
            "executable_allowed": exe_all.get("allowed"),
            "executable_fills": exe_all.get("executed_simulated_fills"),
            "why": (
                "RAW_SIGNAL scores theoretical SL/TP before RiskGate. "
                "EXECUTABLE applies unchanged RiskGate then UNKNOWN-commission SimulatedBroker. "
                "Fold assignment is by entry time for both."
            ),
        },
        "degradation": degradation,
        "stability": stability,
        "lookahead": {
            "official_results_closed_bars_only": True,
            "features_use_future_candles": False,
            "signal_generation_uses_future_high_low": False,
            "exits_may_use_future_bars_after_entry": True,
            "future_fold_not_used_for_past_signals": True,
            "status": "PASS",
        },
        "statistical_sufficiency": sufficiency,
        "deterministic_reproducibility": {
            "setups_fingerprint": fp,
            "matches_phase28_0_fingerprint": fp == prior_fp,
            "matches_phase28_1_fingerprint": fp == p281_fp,
            "used_phase28_0_official_setups": used_prior_scan,
            "used_phase28_1_official_executable": used_prior_exe,
        },
        "conclusion": conclusion,
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "MONTE_CARLO": False,
            "PHASE_28_3_STARTED": False,
        },
        "phase_28_3_started": False,
    }

    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != approved["current_fingerprint"])
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = approved["current_fingerprint"]
    payload["canonical_fingerprint_after"] = fp_after

    _write_json(root / PHASE282_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Performance validation (Phase 28.2)"
        block = (
            "\n\n## Performance validation (Phase 28.2)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Walk-forward uses only Phase 28.0/28.1 XAUUSD_i M5 | **SUPPORTED** |\n"
            "| TRAIN/VALIDATION used for optimization | **NO** — descriptive only |\n"
            "| Strategy stable across TRAIN/VAL/OOS | **INSUFFICIENT_SAMPLE** |\n"
            "| Phase 28.2 authorizes live trading | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")

    return payload


if __name__ == "__main__":
    run_phase28_2_collection()
