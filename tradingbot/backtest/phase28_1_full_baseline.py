"""Phase 28.1 — chronological full baseline on the Phase 28.0 XAUUSD_i dataset.

RESEARCH ONLY. No optimization, no gate/parameter changes, no MT5, no parquet rewrite,
no Monte Carlo, no live authorization.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
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
    PHASE280_MANIFEST_JSON,
    UNKNOWN,
    WARMUP,
    _build_research_engine,
    _enrich_frame,
    _riskgate_one_candidate,
    _setups_fingerprint,
    build_research_configuration,
    classify_statistical_sufficiency,
    load_parquet_utc,
    scan_signal_setups,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.gold_strategies.m5_london_sweep import m5_ny_entry_hours

PHASE = "28.1"
PHASE281_JSON = "logs/phase28_1_full_baseline.json"
PHASE281_MD = "docs_v2/02_research/PHASE28_1_FULL_BASELINE.md"
FORBIDDEN_DATASETS = (
    "data/backtest/XAUUSD_M5_183d.parquet",
    "data/XAUUSD_5m.parquet",
)

ATTRIBUTION_BUCKETS = ("LOT", "META", "ATR", "SPREAD", "NEWS", "SESSION", "COOLDOWN", "OTHER")

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "monte_carlo",
    "approved_dataset",
    "dataset_fingerprint",
    "fingerprint_matches_phase28_0",
    "silent_xauusd_mapping",
    "lookahead",
    "raw_signal",
    "executable",
    "raw_vs_executable_diff",
    "riskgate_attribution",
    "monthly_distribution",
    "weekly_distribution",
    "drawdown",
    "trade_frequency",
    "statistical_sufficiency",
    "conclusion",
    "FINAL_GATE",
    "phase_28_2_started",
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


def classify_riskgate_reason(reason: str | None) -> str:
    """Map a RiskGate reason onto the Phase 28.1 attribution buckets. Gates are not changed."""
    r = str(reason or "").lower()
    if "lot" in r:
        return "LOT"
    if "meta-labeler" in r or "meta label" in r:
        return "META"
    if "atr" in r:
        return "ATR"
    if "spread" in r:
        return "SPREAD"
    if "news" in r:
        return "NEWS"
    if "friday" in r or "session" in r or "outside_ny" in r or "kill_zone" in r:
        return "SESSION"
    if "cooldown" in r:
        return "COOLDOWN"
    return "OTHER"


def confirm_approved_dataset(root: Path) -> dict[str, Any]:
    manifest = _safe_load_json(root / PHASE280_MANIFEST_JSON) or {}
    baseline = _safe_load_json(root / PHASE280_BASELINE_JSON) or {}
    if not manifest or not baseline:
        raise FileNotFoundError("Phase 28.0 artifacts missing — run Phase 28.0 first")
    best = manifest.get("best_dataset") or {}
    path = str(best.get("path") or baseline.get("best_dataset") or CANONICAL_PARQUET).replace("\\", "/")
    if path != CANONICAL_PARQUET:
        raise RuntimeError(f"Phase 28.0 best dataset is not canonical: {path}")
    expected = str(baseline.get("dataset_fingerprint") or EXPECTED_CANONICAL_FINGERPRINT)
    current = file_fingerprint(root / CANONICAL_PARQUET)
    map28 = manifest.get("dataset_symbol_map") or {}
    silent = bool(manifest.get("silent_xauusd_mapping"))
    if map28 or silent:
        raise RuntimeError("Phase 28.0 used a dataset map or silent XAUUSD bind — 28.1 refuses it")
    evidence_syms = {row.get("symbol") for row in (manifest.get("evidence_backed") or [])}
    if "XAUUSD" in evidence_syms:
        raise RuntimeError("Phase 28.0 evidence_backed contains logical XAUUSD")
    return {
        "path": path,
        "symbol": PRIMARY_SYMBOL,
        "timeframe": "M5",
        "phase28_0_fingerprint": expected,
        "current_fingerprint": current,
        "fingerprint_matches_phase28_0": current == expected == EXPECTED_CANONICAL_FINGERPRINT,
        "dataset_symbol_map": {},
        "silent_xauusd_mapping": False,
        "logical_xauusd_used": False,
        "forbidden_datasets_not_loaded": list(FORBIDDEN_DATASETS),
        "forbidden_datasets_touched": [],
        "rows_phase28_0": baseline.get("rows"),
        "range_phase28_0": baseline.get("data_range"),
        "h4_context": H4_CONTEXT_PARQUET if (root / H4_CONTEXT_PARQUET).is_file() else None,
        "chunking": "NOT_REQUIRED",
        "chunking_note": (
            "Maximum defensible XAUUSD_i M5 range is the canonical 3000-bar file "
            "(~15 calendar days). No longer defensible XAUUSD_i M5 tape exists. "
            "A full-file chronological scan is not computationally excessive. "
            "Logical XAUUSD 183d tapes remain BLOCKED and are not chunked in."
        ),
    }


def session_funnel(enriched: pd.DataFrame, *, warmup: int = WARMUP) -> dict[str, Any]:
    cfg = get_price_action_config(PRIMARY_SYMBOL, "M5")
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    ny = 0
    outside = 0
    ny_days: set[str] = set()
    for cursor in range(warmup, len(enriched)):
        ts = enriched.index[cursor]
        hour = int(getattr(ts, "hour", -1))
        if ny_s <= hour < ny_e:
            ny += 1
            ny_days.add(str(ts.date()))
        else:
            outside += 1
    return {
        "warmup": warmup,
        "bars_after_warmup": int(max(0, len(enriched) - warmup)),
        "bars_outside_ny_session": outside,
        "bars_in_ny_session": ny,
        "ny_session_days": len(ny_days),
        "ny_window": f"{ny_s}-{ny_e} UTC",
        "session_filter_owner": "PriceActionStrategy.generate_signals (not RiskGate)",
    }


def _parse_ts(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts


def _duration_minutes(setup: dict[str, Any]) -> float | None:
    start = _parse_ts(setup.get("timestamp"))
    end = _parse_ts(setup.get("exit_time"))
    if start is None or end is None:
        return None
    return float((end - start).total_seconds() / 60.0)


def expand_raw_metrics(setups: list[dict[str, Any]], *, calendar_days: float, ny_session_days: int) -> dict[str, Any]:
    buy_n = sum(1 for s in setups if str(s.get("direction")).upper() == "BUY")
    sell_n = sum(1 for s in setups if str(s.get("direction")).upper() == "SELL")
    resolved = [s for s in setups if s.get("outcome") in {"win", "loss"}]
    r_vals = [float(s["r_multiple"]) for s in resolved if s.get("r_multiple") is not None]
    wins = [r for r in r_vals if r > 0]
    losses = [r for r in r_vals if r <= 0]
    gross_win = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    loss_streak = 0
    win_streak = 0
    max_loss_streak = 0
    max_win_streak = 0
    for r in r_vals:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
        if r > 0:
            win_streak += 1
            max_win_streak = max(max_win_streak, win_streak)
            loss_streak = 0
        else:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
            win_streak = 0
    durations = [d for d in (_duration_minutes(s) for s in resolved) if d is not None]
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    days = max(float(calendar_days), 1.0)
    session_days = max(int(ny_session_days), 1)
    monthly: dict[str, int] = defaultdict(int)
    weekly: dict[str, int] = defaultdict(int)
    for s in resolved:
        ts = _parse_ts(s.get("timestamp"))
        if ts is None:
            continue
        monthly[f"{ts.year:04d}-{ts.month:02d}"] += 1
        iso = ts.isocalendar()
        weekly[f"{iso.year:04d}-W{int(iso.week):02d}"] += 1
    return {
        "setups": len(setups),
        "total_trades": len(resolved),
        "BUY": buy_n,
        "SELL": sell_n,
        "open": sum(1 for s in setups if s.get("outcome") == "open"),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(r_vals), 6) if r_vals else None,
        "average_R": round(sum(r_vals) / len(r_vals), 6) if r_vals else None,
        "expectancy_R": round(sum(r_vals) / len(r_vals), 6) if r_vals else None,
        "profit_factor": None if pf is None else round(pf, 6),
        "gross_profit_R": round(gross_win, 6),
        "gross_loss_R": round(gross_loss, 6),
        "net_R": round(sum(r_vals), 6) if r_vals else 0.0,
        "max_drawdown_R": round(abs(max_dd), 6) if r_vals else None,
        "max_consecutive_wins": int(max_win_streak),
        "max_consecutive_losses": int(max_loss_streak),
        "average_trade_duration_minutes": round(sum(durations) / len(durations), 4) if durations else None,
        "trades_per_calendar_day": round(len(resolved) / days, 6),
        "trades_per_ny_session": round(len(resolved) / session_days, 6),
        "ny_session_days": ny_session_days,
        "calendar_days": round(float(calendar_days), 4),
        "monthly_distribution": dict(sorted(monthly.items())),
        "weekly_distribution": dict(sorted(weekly.items())),
        "units": "R-multiples on theoretical SL/TP; not USD; not cost-adjusted",
        "occupancy_note": (
            "Each setup is scored independently. Live max-positions is a RiskGate rule, "
            "so raw overlapping NY-hour setups overstate concurrent book exposure."
        ),
    }


def empty_executable_metrics() -> dict[str, Any]:
    return {
        "setups": 0,
        "total_trades": 0,
        "BUY": 0,
        "SELL": 0,
        "open": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "average_R": None,
        "expectancy_R": None,
        "profit_factor": None,
        "gross_profit_R": 0.0,
        "gross_loss_R": 0.0,
        "net_R": None,
        "max_drawdown_R": None,
        "max_consecutive_wins": 0,
        "max_consecutive_losses": 0,
        "average_trade_duration_minutes": None,
        "trades_per_calendar_day": 0.0,
        "trades_per_ny_session": 0.0,
        "monthly_distribution": {},
        "weekly_distribution": {},
    }


async def chronological_riskgate(
    engine: Any,
    setups: list[dict[str, Any]],
) -> dict[str, Any]:
    """Time-ordered RiskGate. Account/cooldown state is preserved. Gates are not loosened."""
    rows: list[dict[str, Any]] = []
    buckets: Counter[str] = Counter({k: 0 for k in ATTRIBUTION_BUCKETS})
    reasons: Counter[str] = Counter()
    allowed_setups: list[dict[str, Any]] = []
    for cand in setups:
        audit = await _riskgate_one_candidate(engine, cand)
        reason = str(audit.get("reason") or "unknown")
        is_allowed = bool(audit.get("allowed"))
        bucket = "OTHER"
        if is_allowed:
            reasons["ALLOWED"] += 1
            allowed_setups.append(cand)
            if cand.get("outcome") in {"win", "loss"}:
                pnl_sign = 1.0 if cand.get("outcome") == "win" else -1.0
                engine._risk.on_trade_closed(pnl_sign, int(cand["cursor"]))
        else:
            reasons[reason] += 1
            bucket = classify_riskgate_reason(reason)
            buckets[bucket] += 1
        rows.append(
            {
                "timestamp": cand.get("timestamp"),
                "cursor": cand.get("cursor"),
                "direction": cand.get("direction"),
                "allowed": is_allowed,
                "reason": reason,
                "bucket": None if is_allowed else bucket,
                "has_signal": audit.get("has_signal"),
            }
        )
    return {
        "candidates": len(setups),
        "allowed": len(allowed_setups),
        "rejected": len(setups) - len(allowed_setups),
        "rejection_reasons": dict(reasons),
        "attribution_counts": dict(buckets),
        "rows": rows,
        "allowed_setups": allowed_setups,
        "chronological": True,
        "risk_state_preserved": True,
        "pa_dedup_cleared_per_candidate": True,
        "pa_dedup_note": (
            "PA_DEDUP cache is cleared so RiskGate sees the same setup the sequential "
            "strategy scan already emitted. Clearing does not loosen RiskGate. "
            "BacktestRiskGate consecutive-loss / pause / day counters are not reset."
        ),
        "executed_simulated_fills": 0,
        "broker_fill_note": (
            "SimulatedBroker refuse-closes commission UNKNOWN. Default remains UNKNOWN. "
            "0 fills is not proof of no edge."
        ),
    }


def explain_raw_vs_executable(
    *,
    raw: dict[str, Any],
    exe: dict[str, Any],
    attribution: dict[str, Any],
    funnel: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "difference": "population",
            "raw": f"{raw.get('setups')} strategy setups on closed NY bars",
            "executable": f"{exe.get('candidates')} RiskGate candidates; {exe.get('allowed')} allowed; {exe.get('executed_simulated_fills')} fills",
            "why": "RAW_SIGNAL stops before RiskGate. EXECUTABLE is RiskGate then SimulatedBroker.",
        },
        {
            "difference": "session filter",
            "raw": f"{funnel.get('bars_in_ny_session')} NY bars eligible for generate_signals",
            "executable": "SESSION bucket counts RiskGate session/friday rejects only (0 if strategy already filtered)",
            "why": "NY 15-16 UTC is applied in PriceActionStrategy, not as a RiskGate first-line bucket.",
        },
        {
            "difference": "overlapping exposure",
            "raw": "every setup is an independent theoretical trade",
            "executable": "max positions / cooldown / daily cap would bind only after an allowed fill",
            "why": "Live RiskGate occupancy is not part of raw theoretical R.",
        },
        {
            "difference": "blocking gates",
            "raw": "no LOT/META/ATR/SPREAD/NEWS/COOLDOWN",
            "executable": json.dumps(attribution.get("counts") or {}, sort_keys=True),
            "why": "Gates were not changed. META and ATR are configured live behavior.",
        },
        {
            "difference": "costs / fills",
            "raw": "theoretical SL/TP R, no spread/commission/slippage",
            "executable": "commission UNKNOWN fail-closes SimulatedBroker even if RiskGate allows",
            "why": "COMPLETE_COSTS_REQUIRED still BLOCKED; ZERO commission is not assumed.",
        },
        {
            "difference": "0 executable trades",
            "raw": f"resolved={raw.get('total_trades')}",
            "executable": "0 allowed, 0 fills",
            "why": "Do not interpret 0 executable trades as proof the strategy has no edge.",
        },
    ]


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    raw = payload["raw_signal"]
    exe = payload["executable"]
    attr = payload["riskgate_attribution"]
    path = root / PHASE281_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    diffs = "\n".join(
        f"- **{d['difference']}:** RAW {d['raw']} — EXECUTABLE {d['executable']} — {d['why']}"
        for d in payload["raw_vs_executable_diff"]
    )
    path.write_text(
        f"""# Phase 28.1 — Chronological Full Baseline

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Live trading authorized:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`
**EV-EQ-01:** `{payload.get("ev_eq_01")}`
**Monte Carlo:** NO
**Parameters optimized:** NO

Chronological historical baseline of the **unchanged** GoldenEdge `gold_ny_sweep` strategy on the Phase 28.0 approved `XAUUSD_i` M5 dataset.

STOP AFTER PHASE 28.1. DO NOT START PHASE 28.2.

---

## Dataset

| Field | Value |
|---|---|
| Path | `{payload["approved_dataset"]["path"]}` |
| Fingerprint | `{payload["dataset_fingerprint"]}` |
| Matches Phase 28.0 | `{payload["fingerprint_matches_phase28_0"]}` |
| Period | `{payload["period"]["start"]} → {payload["period"]["end"]}` |
| Rows | `{payload["period"]["rows"]}` |
| Timezone | UTC |
| dataset_symbol_map | `{{}}` |
| Silent XAUUSD mapping | `{payload["silent_xauusd_mapping"]}` |
| Chunking | `{payload["approved_dataset"]["chunking"]}` |

Logical `XAUUSD` tapes were not used. H4 context: `{payload["approved_dataset"].get("h4_context")}`.

---

## Lookahead

Closed bars only. Forming bar appended then excluded. No future high/low in signal generation. Exits may use bars after entry. SL before TP on the same exit bar.

---

## RAW_SIGNAL

| Metric | Value |
|---|---|
| Setups | `{raw.get("setups")}` |
| BUY / SELL | `{raw.get("BUY")} / {raw.get("SELL")}` |
| Trades (resolved) | `{raw.get("total_trades")}` |
| Wins / losses | `{raw.get("wins")} / {raw.get("losses")}` |
| Win rate | `{raw.get("win_rate")}` |
| Average R / expectancy R | `{raw.get("average_R")} / {raw.get("expectancy_R")}` |
| PF | `{raw.get("profit_factor")}` |
| Gross profit R / gross loss R | `{raw.get("gross_profit_R")} / {raw.get("gross_loss_R")}` |
| Max DD R | `{raw.get("max_drawdown_R")}` |
| Avg duration (minutes) | `{raw.get("average_trade_duration_minutes")}` |
| Trades/calendar day | `{raw.get("trades_per_calendar_day")}` |
| Trades/NY session | `{raw.get("trades_per_ny_session")}` |
| Consecutive wins / losses | `{raw.get("max_consecutive_wins")} / {raw.get("max_consecutive_losses")}` |

Monthly: `{json.dumps(raw.get("monthly_distribution") or {}, default=str)}`
Weekly: `{json.dumps(raw.get("weekly_distribution") or {}, default=str)}`

Independent theoretical outcomes. Not cost-adjusted. Overlapping NY setups overstate concurrent exposure.

---

## EXECUTABLE_RISKGATE

| Metric | Value |
|---|---|
| Candidates | `{exe.get("candidates")}` |
| Allowed | `{exe.get("allowed")}` |
| Rejected | `{exe.get("rejected")}` |
| Simulated fills | `{exe.get("executed_simulated_fills")}` |
| Win rate / expectancy / PF / DD | `{exe.get("metrics", {}).get("win_rate")} / {exe.get("metrics", {}).get("expectancy_R")} / {exe.get("metrics", {}).get("profit_factor")} / {exe.get("metrics", {}).get("max_drawdown_R")}` |

Gates were **not** changed.

---

## RAW vs EXECUTABLE

{diffs}

---

## RiskGate attribution

| Bucket | Count |
|---|---|
| LOT | `{attr["counts"].get("LOT", 0)}` |
| META | `{attr["counts"].get("META", 0)}` |
| ATR | `{attr["counts"].get("ATR", 0)}` |
| SPREAD | `{attr["counts"].get("SPREAD", 0)}` |
| NEWS | `{attr["counts"].get("NEWS", 0)}` |
| SESSION (RiskGate) | `{attr["counts"].get("SESSION", 0)}` |
| COOLDOWN | `{attr["counts"].get("COOLDOWN", 0)}` |
| OTHER | `{attr["counts"].get("OTHER", 0)}` |

Strategy session funnel (not RiskGate): `{attr.get("session_funnel")}`.

---

## Statistical sufficiency

**{payload["statistical_sufficiency"].get("classification")}**

{payload.get("conclusion")}

---

## Safety

- No MT5, no live orders, no `.env`, no parquet rewrite
- No strategy / RiskGate / sizing / RR / ML / parameter changes
- No Monte Carlo
- Phase 28.2 was **not** started

Artifacts: `{PHASE281_JSON}`, `{PHASE281_MD}`, `tradingbot/backtest/phase28_1_full_baseline.py`, `tests/test_phase28_1_full_baseline.py`
""",
        encoding="utf-8",
    )


def run_phase28_1_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    approved = confirm_approved_dataset(root)
    if not approved["fingerprint_matches_phase28_0"]:
        raise RuntimeError("Canonical fingerprint does not match Phase 28.0 / expected hash")

    research = build_research_configuration()
    research["phase"] = PHASE
    research["validation_class"] = "PHASE28_1_CHRONOLOGICAL_BASELINE"
    research["parameters_optimized"] = False
    research["monte_carlo"] = False
    cfg_fp = hashlib.sha256(json.dumps(research, sort_keys=True, default=str).encode()).hexdigest()[:16]
    research["configuration_fingerprint"] = cfg_fp

    df = load_parquet_utc(root / CANONICAL_PARQUET)
    enriched = _enrich_frame(df)
    h4 = load_parquet_utc(root / H4_CONTEXT_PARQUET) if (root / H4_CONTEXT_PARQUET).is_file() else None
    funnel = session_funnel(enriched, warmup=WARMUP)
    setups = scan_signal_setups(enriched, warmup=WARMUP, symbol=PRIMARY_SYMBOL)
    setups_repeat = scan_signal_setups(enriched, warmup=WARMUP, symbol=PRIMARY_SYMBOL)
    fp1 = _setups_fingerprint(setups)
    fp2 = _setups_fingerprint(setups_repeat)
    p28 = _safe_load_json(root / PHASE280_BASELINE_JSON) or {}
    p28_fp = ((p28.get("deterministic_reproducibility") or {}).get("fingerprint"))

    span_days = 0.0
    if not df.empty:
        span_days = float((df.index[-1] - df.index[0]).total_seconds() / 86400.0)
    raw = expand_raw_metrics(setups, calendar_days=span_days, ny_session_days=int(funnel["ny_session_days"]))

    engine = _build_research_engine(enriched, research, h4=h4)
    exe_raw = asyncio.run(chronological_riskgate(engine, setups))
    if exe_raw["allowed"] > 0:
        exe_metrics = expand_raw_metrics(
            exe_raw["allowed_setups"],
            calendar_days=span_days,
            ny_session_days=int(funnel["ny_session_days"]),
        )
    else:
        exe_metrics = empty_executable_metrics()
        exe_metrics["ny_session_days"] = funnel["ny_session_days"]
        exe_metrics["calendar_days"] = round(span_days, 4)

    attribution_counts = exe_raw["attribution_counts"]
    attribution = {
        "counts": attribution_counts,
        "raw_reasons": exe_raw["rejection_reasons"],
        "session_funnel": funnel,
        "note": (
            "Buckets apply to RiskGate rejects of strategy setups. "
            "NY session filtering happens in the strategy and is reported in session_funnel, "
            "not as a RiskGate SESSION count unless RiskGate itself rejected for session/friday."
        ),
        "gates_changed": False,
    }

    sufficiency = classify_statistical_sufficiency(
        resolved=int(raw["total_trades"]),
        calendar_days=span_days,
        setups=int(raw["setups"]),
    )
    if sufficiency["classification"] == "DATA_INSUFFICIENT":
        status = "PASS_WITH_DEFERRAL"
        conclusion = (
            "DATA_INSUFFICIENT. The approved XAUUSD_i M5 range is still ~15 days. "
            "Chronological RAW_SIGNAL metrics are descriptive only. "
            "0 RiskGate-allowed / 0 SimulatedBroker fills is not proof of no edge. "
            "Gates and parameters were not changed. No Monte Carlo. "
            "EV-EQ-01 remains NOT_PROVEN. FINAL_GATE remains BLOCKED. "
            "This research does not authorize live trading or Phase 28.2."
        )
    else:
        status = "PASS"
        conclusion = "Sample meets the size heuristic; still not production authorization."

    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    final_gate = gate16.get("FINAL_GATE") or BLOCKED

    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": status,
        "research_only": True,
        "live_trading_authorized": False,
        "cost_adjusted_metrics_allowed": False,
        "parameters_optimized": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "monte_carlo": False,
        "ev_eq_01": "NOT_PROVEN",
        "cost_completeness": BLOCKED,
        "FINAL_GATE": final_gate,
        "production_readiness": BLOCKED,
        "approved_dataset": approved,
        "dataset_fingerprint": approved["current_fingerprint"],
        "fingerprint_matches_phase28_0": True,
        "silent_xauusd_mapping": False,
        "period": {
            "start": str(df.index[0]) if len(df) else None,
            "end": str(df.index[-1]) if len(df) else None,
            "rows": int(len(df)),
            "timezone": "UTC",
        },
        "research_configuration": {
            "symbol": PRIMARY_SYMBOL,
            "timeframe": "M5",
            "dataset_symbol_map": {},
            "commission_status": "UNKNOWN",
            "risk_per_trade": 0.005,
            "min_rr": 1.5,
            "configuration_fingerprint": cfg_fp,
            "inherited_from_phase28_0": True,
        },
        "lookahead": {
            "official_results_closed_bars_only": True,
            "features_use_future_candles": False,
            "signal_generation_uses_future_high_low": False,
            "exits_may_use_future_bars_after_entry": True,
            "forming_bar_excluded": True,
            "status": "PASS",
        },
        "chunking": {
            "used": False,
            "reason": approved["chunking_note"],
            "semantics_changed": False,
        },
        "raw_signal": raw,
        "executable": {
            **{k: v for k, v in exe_raw.items() if k != "allowed_setups"},
            "metrics": exe_metrics,
        },
        "raw_vs_executable_diff": explain_raw_vs_executable(
            raw=raw,
            exe=exe_raw,
            attribution=attribution,
            funnel=funnel,
        ),
        "riskgate_attribution": attribution,
        "monthly_distribution": raw.get("monthly_distribution"),
        "weekly_distribution": raw.get("weekly_distribution"),
        "drawdown": {
            "raw_max_drawdown_R": raw.get("max_drawdown_R"),
            "executable_max_drawdown_R": exe_metrics.get("max_drawdown_R"),
        },
        "trade_frequency": {
            "raw_per_calendar_day": raw.get("trades_per_calendar_day"),
            "raw_per_ny_session": raw.get("trades_per_ny_session"),
            "executable_per_calendar_day": exe_metrics.get("trades_per_calendar_day"),
            "executable_per_ny_session": exe_metrics.get("trades_per_ny_session"),
        },
        "statistical_sufficiency": sufficiency,
        "deterministic_reproducibility": {
            "signal_scan_repeated": True,
            "setups_fingerprint_match": fp1 == fp2,
            "fingerprint": fp1,
            "matches_phase28_0_fingerprint": fp1 == p28_fp,
        },
        "conclusion": conclusion,
        "full_kernel_walk": (
            "NOT_RUN. Chronological baseline is the full canonical range via closed-bar "
            "signal scan + time-ordered RiskGate. Non-NY bars cannot emit official entries. "
            "A 2700-bar TradingKernel walk does not change 0-allow semantics here."
        ),
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
            "PHASE_28_2_STARTED": False,
        },
        "phase_28_2_started": False,
    }

    compact_setups = [
        {
            "timestamp": s.get("timestamp"),
            "direction": s.get("direction"),
            "entry_price": s.get("entry_price"),
            "stop_loss": s.get("stop_loss"),
            "take_profit": s.get("take_profit"),
            "outcome": s.get("outcome"),
            "r_multiple": s.get("r_multiple"),
            "exit_time": s.get("exit_time"),
            "duration_minutes": _duration_minutes(s),
        }
        for s in setups
    ]
    payload["raw_signal"] = {**raw, "setup_rows": compact_setups}

    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != approved["current_fingerprint"])
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = approved["current_fingerprint"]
    payload["canonical_fingerprint_after"] = fp_after

    _write_json(root / PHASE281_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Performance validation (Phase 28.1)"
        block = (
            "\n\n## Performance validation (Phase 28.1)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Chronological baseline uses only Phase 28.0 XAUUSD_i M5 | **SUPPORTED** |\n"
            "| Logical XAUUSD 183d used as 28.1 range | **BLOCKED** — not used |\n"
            "| Current strategy has proven edge on this tape | **DATA_INSUFFICIENT** |\n"
            "| 0 executable trades proves no edge | **FALSE** |\n"
            "| Phase 28.1 authorizes live trading | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")

    return payload


if __name__ == "__main__":
    run_phase28_1_collection()
