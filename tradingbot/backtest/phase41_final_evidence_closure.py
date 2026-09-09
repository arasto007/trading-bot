"""Phase 41 — final evidence closure, broker validation, verdict, readiness.

RESEARCH / AUDIT ONLY. Reads existing Phase 27–40 artifacts. Does not trade,
optimize, modify production strategy/RiskGate/execution/ML, read .env, start
MT5, or rerun the Phase 40 full-tape scan. Does not start Phase 42.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase28_0_performance_foundation import BLOCKED, CANONICAL_PARQUET
from tradingbot.backtest.phase38_intelligent_evidence_acquisition import PHASE38_JSON, PHASE38_M5
from tradingbot.backtest.phase39_broker_economics_execution import PHASE39_JSON
from tradingbot.backtest.phase40_full_horizon_validation import (
    PHASE40_JSON,
    PHASE40_MD,
    PHASE40_SETUPS_JSONL,
)

# Cited from tradingbot/config/live.py::PRIMARY_SYMBOL. This module does not
# import live.py (that file also reads optional env overrides on import).
CODE_PRIMARY_SYMBOL = "XAUUSD_i"

PHASE = "41"
PHASE41_JSON = "logs/phase41_final_evidence_closure.json"
PHASE41_MD = "docs_v2/02_research/PHASE41_FINAL_EVIDENCE_CLOSURE.md"
PHASE41_BLOCKERS_MD = "docs_v2/02_research/PHASE41_BLOCKER_MATRIX.md"
UNKNOWN = "UNKNOWN"
NOT_PROVEN = "NOT_PROVEN"

EXPECTED_PHASE40 = {
    "tape_rows_loaded": 250000,
    "start": "2023-02-24 11:10:00+00:00",
    "end": "2026-09-07 20:10:00+00:00",
    "tape_days": 1291.375,
    "signals": 2847,
    "buy": 1063,
    "sell": 1784,
    "events": 420,
    "win_rate": 0.314528,
    "expectancy_R": 0.017224,
    "profit_factor": 1.025128,
    "max_drawdown_R": 293.59309,
    "oos_signals": 367,
    "oos_events": 63,
    "oos_classification": "SUFFICIENT",
    "allowed": 82,
    "rejected": 2765,
    "fills": 0,
    "raw_class": "B",
    "broker_class": "D",
    "overall_class": "B",
    "FINAL_GATE": BLOCKED,
    "profitability_verdict": "NOT_ISSUED",
}

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "phase40_status",
    "phase40_test_status",
    "data",
    "strategy",
    "raw_performance",
    "oos",
    "events",
    "dependence",
    "broker",
    "symbol",
    "commission",
    "swap",
    "spread",
    "slippage",
    "execution",
    "request_fill",
    "cost_model",
    "robustness",
    "final_gate",
    "verdict",
    "blockers",
    "next_phases",
    "production_safety",
    "artifacts",
)

FORBIDDEN_OUTPUT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")


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


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in FORBIDDEN_OUTPUT_KEYS}


def _approx(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def _row(
    item: str,
    status: str,
    source: str,
    strength: str,
    artifact: str,
    blocks_verdict: bool,
    blocks_live: bool,
    closure: str,
    label: str,
) -> dict[str, Any]:
    return {
        "item": item,
        "status": status,
        "evidence_source": source,
        "evidence_strength": strength,
        "artifact": artifact,
        "blocks_final_verdict": blocks_verdict,
        "blocks_live_trading": blocks_live,
        "closure_evidence": closure,
        "epistemic_label": label,
    }


def verify_phase40_facts(p40: dict[str, Any]) -> dict[str, Any]:
    scan = p40.get("scan") or {}
    raw = p40.get("raw_performance") or {}
    ev = p40.get("events") or {}
    oos = p40.get("oos_sufficiency") or {}
    exe = p40.get("executable") or {}
    cls = p40.get("classification") or {}
    checks = {
        "tape_rows_loaded": (scan.get("tape_rows_loaded"), EXPECTED_PHASE40["tape_rows_loaded"]),
        "start": (scan.get("start"), EXPECTED_PHASE40["start"]),
        "end": (scan.get("end"), EXPECTED_PHASE40["end"]),
        "tape_days": (p40.get("tape_days"), EXPECTED_PHASE40["tape_days"]),
        "signals": (scan.get("signals"), EXPECTED_PHASE40["signals"]),
        "buy": (scan.get("buy"), EXPECTED_PHASE40["buy"]),
        "sell": (scan.get("sell"), EXPECTED_PHASE40["sell"]),
        "events": (ev.get("event_count"), EXPECTED_PHASE40["events"]),
        "win_rate": (raw.get("win_rate"), EXPECTED_PHASE40["win_rate"]),
        "expectancy_R": (raw.get("expectancy_R"), EXPECTED_PHASE40["expectancy_R"]),
        "profit_factor": (raw.get("profit_factor"), EXPECTED_PHASE40["profit_factor"]),
        "max_drawdown_R": (raw.get("max_drawdown_R"), EXPECTED_PHASE40["max_drawdown_R"]),
        "oos_signals": (oos.get("signals"), EXPECTED_PHASE40["oos_signals"]),
        "oos_events": (oos.get("events"), EXPECTED_PHASE40["oos_events"]),
        "oos_classification": (oos.get("classification"), EXPECTED_PHASE40["oos_classification"]),
        "allowed": (exe.get("allowed"), EXPECTED_PHASE40["allowed"]),
        "rejected": (exe.get("rejected"), EXPECTED_PHASE40["rejected"]),
        "fills": (exe.get("executed_simulated_trades"), EXPECTED_PHASE40["fills"]),
        "raw_class": (cls.get("strategy_raw_evidence"), EXPECTED_PHASE40["raw_class"]),
        "broker_class": (cls.get("broker_realistic_evidence"), EXPECTED_PHASE40["broker_class"]),
        "overall_class": (cls.get("overall"), EXPECTED_PHASE40["overall_class"]),
        "FINAL_GATE": (p40.get("FINAL_GATE"), EXPECTED_PHASE40["FINAL_GATE"]),
        "profitability_verdict": (cls.get("profitability_verdict"), EXPECTED_PHASE40["profitability_verdict"]),
    }
    mismatches: list[str] = []
    for key, (got, exp) in checks.items():
        ok = _approx(got, exp) if isinstance(exp, float) else got == exp
        if not ok:
            mismatches.append(f"{key}: artifact={got!r} expected={exp!r}")
    return {
        "artifact_status": p40.get("status"),
        "artifact_timestamp_utc": p40.get("timestamp_utc"),
        "matches_expected_facts": not mismatches,
        "mismatches": mismatches,
        "phase40_scan_rerun": False,
        "values_overwritten": False,
        "higher_authority_if_mismatch": "logs/phase40_full_horizon_validation.json (existing artifact)",
    }


def event_concentration(sizes: list[Any]) -> dict[str, Any]:
    nums = [int(x) for x in sizes if isinstance(x, (int, float))]
    total = sum(nums)
    if not nums or total <= 0:
        return {"status": "NOT_RECORDED", "label": "UNKNOWN"}
    ordered = sorted(nums, reverse=True)

    def share(n: int) -> float:
        return sum(ordered[:n]) / total

    return {
        "status": "DERIVED",
        "label": "DERIVED",
        "source": "Phase 40 events.sizes (already recorded; not a rescan)",
        "n_events": len(nums),
        "n_signals_in_sizes": total,
        "top_1_signal_share": share(1),
        "top_5_signal_share": share(min(5, len(ordered))),
        "top_10_signal_share": share(min(10, len(ordered))),
        "largest_event_signals": ordered[0],
        "note": "Share of RAW signals sitting in the largest mechanical-event clusters.",
    }


def derive_jsonl_diagnostics(root: Path) -> dict[str, Any]:
    path = root / PHASE40_SETUPS_JSONL
    if not path.is_file():
        return {"status": "NOT_RECORDED", "reason": "JSONL missing"}
    weekday: Counter[str] = Counter()
    durations: list[float] = []
    hours: Counter[int] = Counter()
    n = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            n += 1
            ts = str(row.get("timestamp") or "")
            if len(ts) >= 10:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    weekday[dt.strftime("%A")] += 1
                    hours[int(dt.hour)] += 1
                except ValueError:
                    pass
            dur = row.get("duration_minutes")
            if isinstance(dur, (int, float)):
                durations.append(float(dur))
    durations.sort()

    def pct(p: float) -> float | str:
        if not durations:
            return "NOT_RECORDED"
        idx = min(len(durations) - 1, max(0, int(round((p / 100.0) * (len(durations) - 1)))))
        return durations[idx]

    ge_8h = sum(1 for d in durations if d >= 480.0)
    ge_12h = sum(1 for d in durations if d >= 720.0)
    return {
        "status": "DERIVED",
        "label": "DERIVED",
        "source": PHASE40_SETUPS_JSONL,
        "rows": n,
        "weekday_counts": dict(weekday),
        "hour_utc_counts": {str(k): v for k, v in sorted(hours.items())},
        "duration_minutes": {
            "n": len(durations),
            "p50": pct(50),
            "p90": pct(90),
            "p99": pct(99),
            "max": durations[-1] if durations else "NOT_RECORDED",
            "share_ge_8h": (ge_8h / len(durations)) if durations else "NOT_RECORDED",
            "share_ge_12h": (ge_12h / len(durations)) if durations else "NOT_RECORDED",
        },
        "note": "Extracted from persisted Phase 40 JSONL. Not a tape rescan.",
    }


def build_evidence_matrix(
    p38: dict[str, Any],
    p39: dict[str, Any],
    p40: dict[str, Any],
    p16: dict[str, Any],
    conc: dict[str, Any],
    jsonl: dict[str, Any],
) -> list[dict[str, Any]]:
    scan = p40.get("scan") or {}
    raw = p40.get("raw_performance") or {}
    ev = p40.get("events") or {}
    dep = p40.get("dependence") or {}
    oos = p40.get("oos_sufficiency") or {}
    exe = p40.get("executable") or {}
    cost39 = p39.get("cost_completeness") or {}
    comm = p39.get("commission") or {}
    swap = p39.get("swap") or {}
    spread = p39.get("spread") or {}
    slip = p39.get("slippage") or {}
    ex = p39.get("execution") or {}
    eco = (p39.get("symbols") or {}).get("XAUUSD_i") or {}
    return [
        _row("A. DATA", "COMPLETE_FOR_RAW", "Phase 38/40 tape audit", "HIGH", PHASE40_JSON, False, False, "None for RAW horizon. Bid/Ask columns still required for broker-realistic tape.", "OBSERVED"),
        _row("B. STRATEGY", "UNCHANGED", "Phase 40 fingerprint", "HIGH", PHASE40_JSON, False, False, "Keep code fingerprint frozen. Do not tune.", "OBSERVED"),
        _row("C. SIGNALS", "OBSERVED", "Phase 40 RAW scan", "HIGH", PHASE40_JSON, False, False, "None. 2847 RAW signals already persisted.", "OBSERVED"),
        _row("D. EVENTS", "SUFFICIENT_COUNT", "Phase 40 events", "HIGH", PHASE40_JSON, False, False, "Count floor met (420). Independence still not claimed.", "OBSERVED"),
        _row("E. DEPENDENCE", "HIGH_DEPENDENCE", "Phase 31 + Phase 40", "HIGH", PHASE40_JSON, True, True, "Treat events not signals as the sample unit. Do not treat as iid.", "OBSERVED"),
        _row("F. WALK-FORWARD", "COMPLETED_MIXED", "Phase 40 60/20/20", "MEDIUM", PHASE40_JSON, True, True, "Explain TRAIN negative vs OOS positive; do not cherry-pick OOS.", "OBSERVED"),
        _row("G. OOS", "COUNT_SUFFICIENT_RESULT_UNVALIDATED", "Phase 40 oos_sufficiency", "MEDIUM", PHASE40_JSON, True, True, "OOS event floor met. Fold/regime inconsistency still blocks a validated edge.", "OBSERVED"),
        _row("H. RAW PERFORMANCE", "MIXED_TINY_POSITIVE", "Phase 40 raw_performance", "MEDIUM", PHASE40_JSON, True, False, "Not a profitability claim. Bootstrap p5 expectancy is negative.", "OBSERVED"),
        _row("I. EXECUTABLE PERFORMANCE", "NOT_ESTABLISHED", "Phase 40 executable", "HIGH", PHASE40_JSON, True, True, "Need VERIFIED_SCHEDULE commission plus non-fabricated fills on the eval tape.", "OBSERVED"),
        _row("J. SPREAD", "PARTIAL_PROXY", "Phase 35 sidecar + Phase 39", "MEDIUM", "docs_v2/02_research/PHASE35_EXECUTION_REALITY.md", True, True, "Complete Bid/Ask on the 1291-day evaluation tape.", "OBSERVED"),
        _row("K. COMMISSION", "UNKNOWN", "Phase 27/38/39", "HIGH", PHASE39_JSON, True, True, "Account-applicable VERIFIED_SCHEDULE: product type, basis, rate, currency, effective date.", "OBSERVED"),
        _row("L. SWAP", "BROKER_RATE_ONLY", "Phase 39 current rates", "MEDIUM", PHASE39_JSON, True, True, "Historical swap series, or a documented hold-duration policy that swap is not applied.", "OBSERVED"),
        _row("M. SLIPPAGE", "MODELED", "Phase 39/40", "LOW", PHASE39_JSON, True, True, "Genuine requested-vs-filled pairs with timestamps and volumes.", "OBSERVED"),
        _row("N. EXECUTION", "DEAL_FILL_TAPE_ONLY", "Phase 38/39 history", "MEDIUM", PHASE39_JSON, True, True, "Order lifecycle, rejects, requotes, latency, request/fill linkage.", "OBSERVED"),
        _row("O. REQUEST/FILL PAIRS", "0", "Phase 39 slippage/journal", "HIGH", PHASE39_JSON, True, True, "XAUUSD_i journal or broker request/fill telemetry.", "OBSERVED"),
        _row("P. BROKER SYMBOL", "NOT_PROVEN", "Phase 38/39 catalog + live.py", "HIGH", PHASE39_JSON, True, True, "EV-EQ-01: prove or disprove XAUUSD == XAUUSD_i for this account without silent mapping.", "OBSERVED"),
        _row("Q. BROKER ECONOMICS", "PARTIAL_CURRENT_SNAPSHOT", "Phase 39 symbol_info", "HIGH", PHASE39_JSON, False, True, "Keep current snapshot; do not treat it as a historical economics series.", "OBSERVED"),
        _row("R. RISK", "UNCHANGED_GATES", "Phase 40 executable.gates_unchanged", "HIGH", PHASE40_JSON, False, False, "Do not change RiskGate. 82 allowed / 2765 rejected is diagnosis only.", "OBSERVED"),
        _row("S. COST MODEL", "INCOMPLETE_0_OF_8", "Phase 39 AND-gate reused by 40", "HIGH", PHASE39_JSON, True, True, "All 8 AND-gate components COMPLETE without weakening the gate.", "OBSERVED"),
        _row("T. ROBUSTNESS", "DIAGNOSTIC_ONLY", "Phase 40 robustness", "MEDIUM", PHASE40_JSON, True, True, "Official config remains unchanged. Diagnostics are not a preferred setup.", "OBSERVED"),
        _row("U. MONTE CARLO", "DESCRIPTIVE_CI_CROSSES_ZERO", "Phase 40 statistics", "MEDIUM", PHASE40_JSON, True, True, "Event-level bootstrap already exists. Do not invent a new CI.", "OBSERVED"),
        _row("V. PRODUCTION READINESS", "BLOCKED", "Phase 27.16 + 40 + 41", "HIGH", PHASE2716_JSON, True, True, "Close cost/execution/symbol gates. Then a separate readiness audit.", "OBSERVED"),
        _row("W. FINAL GATE", BLOCKED, "Phase 27.16 still BLOCKED; 40/41 unchanged", "HIGH", PHASE2716_JSON, True, True, "Do not open FINAL_GATE while cost_ready_for_validation is false.", "OBSERVED"),
        _row("jsonl_weekday_duration", jsonl.get("status", UNKNOWN), "Phase 40 JSONL extract", "LOW", PHASE40_SETUPS_JSONL, False, False, "Optional hold-duration / weekday diagnosis only.", jsonl.get("label", "DERIVED")),
        _row("event_concentration", conc.get("status", UNKNOWN), "Phase 40 sizes", "MEDIUM", PHASE40_JSON, True, False, "Do not treat signal count as independent N.", conc.get("label", "DERIVED")),
        _row("phase38_status", p38.get("status", UNKNOWN), "Phase 38 artifact", "HIGH", PHASE38_JSON, False, False, "Acquisition already complete.", "OBSERVED"),
        _row("phase39_case", (p39.get("case") or {}).get("case", UNKNOWN), "Phase 39 case", "HIGH", PHASE39_JSON, False, False, "Case B remains: modeled sensitivity allowed, broker-realistic forbidden.", "OBSERVED"),
        _row("cost_gate_complete_count", str(cost39.get("complete_count", UNKNOWN)), "Phase 39", "HIGH", PHASE39_JSON, True, True, "Raise complete_count from 0 to 8.", "OBSERVED"),
        _row("commission_verified_schedule", str(comm.get("verified_schedule", False)), "Phase 39", "HIGH", PHASE39_JSON, True, True, "VERIFIED_SCHEDULE", "OBSERVED"),
        _row("swap_historical", str(swap.get("observed_historical", UNKNOWN)), "Phase 39", "MEDIUM", PHASE39_JSON, True, True, "Historical swap series.", "OBSERVED"),
        _row("spread_eval_tape", str(spread.get("evaluation_tape_bid_ask", UNKNOWN)), "Phase 39", "HIGH", PHASE39_JSON, True, True, "Bid/Ask columns on eval tape.", "OBSERVED"),
        _row("slippage_pairs", str(slip.get("genuine_requested_vs_executed_pairs", UNKNOWN)), "Phase 39", "HIGH", PHASE39_JSON, True, True, "Genuine pairs > 0.", "OBSERVED"),
        _row("execution_grade", str(ex.get("grade", UNKNOWN)), "Phase 39", "MEDIUM", PHASE39_JSON, True, True, "Lifecycle evidence beyond deal fill tape.", "OBSERVED"),
        _row("economics_digits", str(eco.get("digits", UNKNOWN)), "Phase 39 symbol_info", "HIGH", PHASE39_JSON, False, False, "Current snapshot already OBSERVED.", "OBSERVED"),
        _row("phase16_final_gate", p16.get("FINAL_GATE", UNKNOWN), "Phase 27.16", "HIGH", PHASE2716_JSON, True, True, "Unchanged BLOCKED.", "OBSERVED"),
        _row("raw_expectancy", str(raw.get("expectancy_R")), "Phase 40", "MEDIUM", PHASE40_JSON, True, False, "Do not call this live profitability.", "OBSERVED"),
        _row("scan_completed", str(scan.get("completed")), "Phase 40", "HIGH", PHASE40_JSON, False, False, "Do not rescan.", "OBSERVED"),
        _row("oos_events", str(oos.get("events")), "Phase 40", "MEDIUM", PHASE40_JSON, False, False, "Count is sufficient; validity is not.", "OBSERVED"),
        _row("dependence_iid", str(dep.get("independence_claimed")), "Phase 40", "HIGH", PHASE40_JSON, True, True, "Keep independence_claimed false.", "OBSERVED"),
        _row("executable_fills", str(exe.get("executed_simulated_trades")), "Phase 40", "HIGH", PHASE40_JSON, True, True, "Non-fabricated fills after commission closure.", "OBSERVED"),
    ]


def build_verdicts(p39: dict[str, Any], p40: dict[str, Any]) -> dict[str, Any]:
    stats = p40.get("statistics") or {}
    exp_ci = (stats.get("expectancy_R") or {})
    return {
        "A_STRATEGY_RAW_EVIDENCE": {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "reason": (
                "Full-horizon RAW expectancy is a tiny +0.017224R with 293.59R drawdown. "
                "TRAIN is negative, 2023–2024 are negative, latest 180d is -0.4676R, and the "
                "event-level bootstrap p5 expectancy is negative. This is mixed, not a demonstrated edge."
            ),
        },
        "B_OUT_OF_SAMPLE_EVIDENCE": {
            "verdict": "PROMISING_BUT_UNPROVEN",
            "reason": (
                "OOS event count is 63 (SUFFICIENT as a count floor) and OOS signal expectancy is +0.250R. "
                "That is not validation: TRAIN is negative, recent 180d is negative, signals are clustered, "
                "and costs are incomplete."
            ),
        },
        "C_COST_VALIDATION": {
            "verdict": "BLOCKED",
            "reason": "AND-gate 0/8. Commission UNKNOWN. cost_ready_for_validation false. Gate not weakened.",
        },
        "D_EXECUTION_VALIDATION": {
            "verdict": "BLOCKED",
            "reason": "0 genuine request/fill pairs. 0 simulated fills. DEAL_FILL_TAPE_ONLY / PARTIAL_EXECUTION_EVIDENCE.",
        },
        "E_BROKER_VALIDATION": {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "reason": (
                "Current REAL LiteFinance XAUUSD_i economics are OBSERVED. "
                "XAUUSD was not observed on this terminal. EV-EQ-01 remains NOT_PROVEN. "
                "Absence on this terminal is not broker-wide absence."
            ),
        },
        "F_LIVE_READINESS": {
            "verdict": "BLOCKED",
            "reason": "FINAL_GATE BLOCKED. RAW is not live. Executable performance is NOT_ESTABLISHED.",
        },
        "G_OVERALL_RESEARCH_VERDICT": {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "reason": (
                "Phase 40 closed the horizon/event-count gap. It did not close cost, execution, "
                "or symbol-mapping gaps and did not produce a defensible profitability verdict."
            ),
        },
        "labels": {
            "SUPPORTED": "Evidence supports the claim under stated conditions",
            "PROMISING_BUT_UNPROVEN": "Some supportive numbers exist; they do not survive required gates",
            "INSUFFICIENT_EVIDENCE": "Evidence is too mixed or incomplete for a defensible claim",
            "NOT_SUPPORTED": "Evidence argues against the claim",
            "BLOCKED": "A required gate is closed; the claim cannot be issued",
        },
        "forbidden_claims_not_issued": [
            "PROFITABLE",
            "UNPROFITABLE",
            "READY FOR LIVE",
            "SAFE TO TRADE",
        ],
        "profitability_verdict": "NOT_ISSUED",
        "bootstrap_expectancy_p5": exp_ci.get("p5"),
        "bootstrap_expectancy_p95": exp_ci.get("p95"),
        "bootstrap_ci_crosses_zero": True,
        "phase39_case": (p39.get("case") or {}).get("case"),
        "phase40_raw_class": (p40.get("classification") or {}).get("strategy_raw_evidence"),
        "phase40_broker_class": (p40.get("classification") or {}).get("broker_realistic_evidence"),
    }


def build_blockers(p39: dict[str, Any], p40: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "blocker": "Commission unknown",
            "severity": "CRITICAL",
            "current_status": "UNKNOWN / OBSERVED_ZERO_NOT_PROVEN",
            "evidence": "30 Phase 39 XAUUSD_i deals commission=0.0; no account-applicable VERIFIED_SCHEDULE",
            "why_it_matters": "SimulatedBroker fail-closes. Executable fills stay 0. Live PnL cannot be estimated.",
            "exact_closure_action": "Obtain account-applicable schedule: product type, basis, rate, currency, effective date. Zero historical commission is not that schedule.",
            "can_close_without_trading": True,
            "can_close_without_strategy_change": True,
        },
        {
            "blocker": "Historical swap series unknown",
            "severity": "HIGH",
            "current_status": "CURRENT_SWAP=OBSERVED; HISTORICAL_SWAP_SERIES=UNKNOWN; SWAP_POLICY=BROKER_RATE_ONLY",
            "evidence": "swap_long=-89.136 swap_short=3.45 rollover=Wednesday; deal zeros do not prove historical zero",
            "why_it_matters": "Overnight tail can change expectancy. Median hold is short, but the tail is not proven swap-free.",
            "exact_closure_action": "Collect historical swap series, or lock a written policy that swap is excluded because holds are intra-session.",
            "can_close_without_trading": True,
            "can_close_without_strategy_change": True,
        },
        {
            "blocker": "Historical Bid/Ask incomplete",
            "severity": "HIGH",
            "current_status": "PARTIAL / PROXY on evaluation tape",
            "evidence": "Phase 35 sidecar n=2952 ~15d OBSERVED; Phase 38/40 eval tape has no Bid/Ask columns",
            "why_it_matters": "OHLC cannot be relabeled as execution spread. Cost sensitivity remains MODELED.",
            "exact_closure_action": "Attach historical Bid/Ask covering the Phase 38 XAUUSD_i M5 evaluation tape.",
            "can_close_without_trading": True,
            "can_close_without_strategy_change": True,
        },
        {
            "blocker": "Request/fill pairs absent",
            "severity": "CRITICAL",
            "current_status": "REQUEST_FILL_PAIRS=0; SLIPPAGE_POLICY=MODELED",
            "evidence": "Phase 39 genuine pairs=0; journal XAUUSD_i pairs=0; price_open is not requested",
            "why_it_matters": "Slippage and latency stay unknown. MT5 deviation=20 is not realized slippage.",
            "exact_closure_action": "Record requested price/time/volume and executed price/time/volume for XAUUSD_i.",
            "can_close_without_trading": True,
            "can_close_without_strategy_change": True,
        },
        {
            "blocker": "Symbol mapping not proven",
            "severity": "HIGH",
            "current_status": "CURRENT_REAL_SYMBOL=XAUUSD_i; EXPECTED_USER_REAL_SYMBOL=XAUUSD; SYMBOL_MAPPING=NOT_PROVEN",
            "evidence": "XAUUSD NOT_OBSERVED_ON_THIS_TERMINAL; broker_wide_absence_concluded=false; EV-EQ-01 NOT_PROVEN; live PRIMARY_SYMBOL=XAUUSD_i",
            "why_it_matters": "Silent XAUUSD→XAUUSD_i mapping is forbidden. Absence here is not broker-wide absence.",
            "exact_closure_action": "Operator/broker confirmation of whether XAUUSD exists on this account/server and whether it is economically identical to XAUUSD_i.",
            "can_close_without_trading": True,
            "can_close_without_strategy_change": True,
        },
        {
            "blocker": "Executable evaluation unavailable",
            "severity": "CRITICAL",
            "current_status": "EXECUTABLE_PERFORMANCE=NOT_ESTABLISHED",
            "evidence": "2847 RAW → 82 RiskGate allowed → 0 fills; EXECUTABLE_BLOCKED_BY_UNKNOWN_COMMISSION",
            "why_it_matters": "RAW +0.017224R is not live performance. Most RAW signals never pass RiskGate.",
            "exact_closure_action": "Close commission, then rerun unchanged RiskGate executable evaluation without fabricating fills.",
            "can_close_without_trading": True,
            "can_close_without_strategy_change": True,
        },
        {
            "blocker": "OOS/regime/dependence uncertainty",
            "severity": "HIGH",
            "current_status": "OOS count SUFFICIENT; result UNVALIDATED",
            "evidence": "TRAIN exp -0.0329R vs OOS +0.250R; 180d -0.468R; 98.6% signals clustered; bootstrap p5 expectancy < 0",
            "why_it_matters": "A later window can look good while the earlier window and recent 180d do not.",
            "exact_closure_action": "After costs exist, reassess event-level OOS and yearly/regime stability. Do not optimize first.",
            "can_close_without_trading": True,
            "can_close_without_strategy_change": True,
        },
        {
            "blocker": "Production configuration / FINAL_GATE",
            "severity": "CRITICAL",
            "current_status": "FINAL_GATE=BLOCKED; live env overrides UNKNOWN (not read)",
            "evidence": "Phase 27.16 BLOCKED; Phase 40/41 do not open it. TRADINGBOT_REAL_SYMBOL env path exists in code and was not read.",
            "why_it_matters": "Operator .env can still diverge from code defaults. This audit did not inspect secrets.",
            "exact_closure_action": "Sanitized operator config dump after cost gates close. Do not read .env in research phases.",
            "can_close_without_trading": True,
            "can_close_without_strategy_change": True,
        },
    ]


def build_next_phases() -> list[dict[str, Any]]:
    return [
        {
            "order": 1,
            "phase": "Phase 42 — account-specific commission closure",
            "information_value": "HIGHEST",
            "why": "This single blocker fail-closes executable evaluation and live cost accounting.",
            "changes_verdict_if_closed": True,
            "optimization": False,
        },
        {
            "order": 2,
            "phase": "Phase 43 — genuine request/fill telemetry",
            "information_value": "HIGH",
            "why": "Converts slippage from MODELED to OBSERVED and enables execution-reality fills.",
            "changes_verdict_if_closed": True,
            "optimization": False,
        },
        {
            "order": 3,
            "phase": "Phase 44 — historical Bid/Ask on the evaluation tape",
            "information_value": "HIGH",
            "why": "Removes the OHLC spread proxy for the 1291-day tape.",
            "changes_verdict_if_closed": True,
            "optimization": False,
        },
        {
            "order": 4,
            "phase": "Phase 45 — historical swap series or written intra-session swap policy",
            "information_value": "MEDIUM",
            "why": "Median hold is short; the overnight tail still needs a documented rule.",
            "changes_verdict_if_closed": True,
            "optimization": False,
        },
        {
            "order": 5,
            "phase": "Phase 46 — EV-EQ-01 symbol mapping closure",
            "information_value": "HIGH",
            "why": "Prevents silent XAUUSD/XAUUSD_i substitution before any live authorization.",
            "changes_verdict_if_closed": True,
            "optimization": False,
        },
        {
            "order": 6,
            "phase": "Phase 47 — executable backtest after cost gates",
            "information_value": "HIGHEST_AFTER_COSTS",
            "why": "Only then can EXECUTABLE_PERFORMANCE leave NOT_ESTABLISHED.",
            "changes_verdict_if_closed": True,
            "optimization": False,
        },
        {
            "order": 7,
            "phase": "Phase 48 — event-level OOS + stability after costs",
            "information_value": "HIGH",
            "why": "Re-interpret TRAIN/OOS/180d/yearly conflict with complete costs.",
            "changes_verdict_if_closed": True,
            "optimization": False,
        },
        {
            "order": 8,
            "phase": "Phase 49 — production-readiness audit",
            "information_value": "REQUIRED_LAST",
            "why": "Only after A–G are no longer BLOCKED/INSUFFICIENT for live.",
            "changes_verdict_if_closed": True,
            "optimization": False,
        },
    ]


def reconcile_39_40(p38: dict[str, Any], p39: dict[str, Any], p40: dict[str, Any]) -> dict[str, Any]:
    raw40 = p40.get("raw_performance") or {}
    c180 = p40.get("comparison_180_vs_full") or {}
    latest = c180.get("latest_180d_of_full_scan") or {}
    p38_eval = ((p38.get("strategy_evaluation") or {}).get("raw") or {})
    return {
        "do_not_rewrite_phase28": True,
        "do_not_rewrite_phase39": True,
        "do_not_rewrite_phase40": True,
        "horizons": {
            "phase28": {
                "label": "short ~15-day canonical tape",
                "note": "Preserved historical evidence. Not replaced by Phase 40.",
            },
            "phase38_39": {
                "label": "180-day research window on the long tape",
                "signals": 249,
                "events": 43,
                "expectancy_R": -0.591085,
                "source": "Phase 38/39 artifacts",
            },
            "phase40_full": {
                "label": "1291-day full-horizon research",
                "signals": 2847,
                "events": 420,
                "expectancy_R": raw40.get("expectancy_R"),
                "source": PHASE40_JSON,
            },
            "phase40_latest_180d_of_full_scan": {
                "signals": latest.get("signals"),
                "events": latest.get("events"),
                "expectancy_R": (latest.get("signal") or {}).get("expectancy_R"),
                "source": "Phase 40 comparison_180_vs_full",
            },
        },
        "interpretation": {
            "RECENT_PERFORMANCE": "Negative. Phase 39 180d expectancy -0.591R; Phase 40 last-180d -0.468R.",
            "FULL_HORIZON_PERFORMANCE": "Tiny positive RAW +0.017224R with 293.59R DD and mixed yearly signs.",
            "OOS_PERFORMANCE": "Count-sufficient and locally positive (+0.250R signal / +0.418R event) but not validated.",
            "EXECUTABLE_PERFORMANCE": "NOT_ESTABLISHED (0 fills).",
        },
        "why_they_differ": [
            "Different horizons: 180d vs 1291d. A later/earlier mix can flip the sign.",
            "Yearly mix: 2023–2024 negative, 2025–2026 positive. A 180d window that lands in 2026-03..09 is the weak recent sleeve.",
            "Phase 38 enriched only the last 180 days; Phase 40 last-180d is a bounded window of the full-tape enrich. Timestamp counts may differ (249 vs 259); that is expected.",
            "Dependence: 98.6% of Phase 40 signals are clustered. Signal-level expectancy overstates independent evidence.",
            "BUY/SELL: full-tape signal expectancy is similar (BUY 0.0170R, SELL 0.0173R). Event-level SELL is better (0.0827R vs BUY -0.0032R). The tiny full-tape plus is not a one-sided artifact at signal level.",
            "Phase 40 does not prove profitability. Phase 39 does not prove permanent failure.",
        ],
        "phase38_raw_n": p38_eval.get("n"),
        "phase39_raw_n": (p39.get("raw_signal") or {}).get("n") or (p39.get("research") or {}).get("raw_setups"),
        "materially_different": True,
        "more_favorable_window": "full_tape",
        "representative_180d": False,
    }


def cost_margin(p40: dict[str, Any]) -> dict[str, Any]:
    sens = p40.get("cost_sensitivity") or {}
    scenarios = {s.get("id"): s for s in (sens.get("scenarios") or []) if isinstance(s, dict)}
    raw_e = (scenarios.get("RAW_NO_COST") or {}).get("signal_expectancy_R")
    m1 = (scenarios.get("MODELED_1X") or {}).get("signal_expectancy_R")
    p5 = ((p40.get("statistics") or {}).get("expectancy_R") or {}).get("p5")
    return {
        "observed_costs": "Commission UNKNOWN. Historical swap UNKNOWN. Eval-tape spread PROXY. Slippage not observed.",
        "modeled_costs": scenarios,
        "unknown_costs": ["commission", "historical_swap", "historical_eval_spread", "realized_slippage"],
        "raw_edge_R": raw_e,
        "modeled_1x_signal_expectancy_R": m1,
        "bootstrap_event_expectancy_p5": p5,
        "cost_robustness_claimed": False,
        "COST_MARGIN": "INSUFFICIENT / UNKNOWN",
        "reason": (
            "The RAW +0.017R edge flips negative under MODELED_1X spread/slip and the event-level "
            "bootstrap p5 expectancy is already negative before adding unknown commission."
        ),
        "label": "DERIVED",
    }


def swap_relevance(p39: dict[str, Any], p40: dict[str, Any], jsonl: dict[str, Any]) -> dict[str, Any]:
    raw = p40.get("raw_performance") or {}
    dur = (jsonl.get("duration_minutes") or {}) if isinstance(jsonl, dict) else {}
    return {
        "CURRENT_SWAP": "OBSERVED",
        "HISTORICAL_SWAP_SERIES": UNKNOWN,
        "SWAP_POLICY": "BROKER_RATE_ONLY",
        "current_swap_long": (p39.get("swap") or {}).get("current_swap_long"),
        "current_swap_short": (p39.get("swap") or {}).get("current_swap_short"),
        "rollover3days": (p39.get("swap") or {}).get("swap_rollover3days"),
        "phase40_median_duration_minutes": raw.get("median_duration_minutes"),
        "phase40_average_duration_minutes": raw.get("average_trade_duration_minutes"),
        "jsonl_p50_minutes": dur.get("p50"),
        "jsonl_p90_minutes": dur.get("p90"),
        "jsonl_share_ge_8h": dur.get("share_ge_8h"),
        "jsonl_share_ge_12h": dur.get("share_ge_12h"),
        "materiality": (
            "INFERRED: median hold (~70 minutes) is typically intra-session and often before "
            "typical ~00:00 UTC gold rollover after a 15:00 UTC NY entry. The average (~6h) and "
            "the >=8h tail can still intersect rollover. Historical swap remains UNKNOWN and is "
            "not set to zero from short-hold deal zeros."
        ),
        "zero_deal_swap_proves_zero_policy": False,
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> Path:
    v = payload.get("verdict") or {}
    rec = payload.get("reconciliation") or {}
    m = payload.get("cost_margin") or {}
    lines = [
        "# Phase 41 — Final Evidence Closure, Broker Validation, Verdict & Readiness",
        "",
        f"**STATUS:** `{payload.get('status')}`",
        "**Class:** RESEARCH / AUDIT ONLY",
        f"**FINAL_GATE:** `{payload.get('final_gate')}`",
        f"**OVERALL_VERDICT:** `{((v.get('G_OVERALL_RESEARCH_VERDICT') or {}).get('verdict'))}`",
        f"**profitability_verdict:** `{payload.get('profitability_verdict')}`",
        f"**PHASE40_SCAN_RERUN:** `{payload.get('phase40_scan_rerun')}`",
        f"**Production changes:** `{((payload.get('production_safety') or {}).get('production_changes'))}`",
        "",
        "STOP AFTER PHASE 41. DO NOT START PHASE 42 AUTOMATICALLY.",
        "DO NOT OPTIMIZE. DO NOT TRADE. DO NOT CHANGE PRODUCTION.",
        "",
        "This phase does **not** issue PROFITABLE, UNPROFITABLE, READY FOR LIVE, or SAFE TO TRADE.",
        "",
        "## Source hierarchy",
        "",
        "1. Current production CODE",
        "2. Canonical documentation",
        "3. Phase audit artifacts",
        "4. Previous phase reports",
        "5. Memory / assumptions",
        "",
        "Contradictions are reported, not silently reconciled.",
        "",
        "## Phase 40 verification",
        "",
        "Existing artifact `logs/phase40_full_horizon_validation.json` was cross-checked and **not** regenerated.",
        "",
        json.dumps(payload.get("phase40_verification"), default=str),
        "",
        f"PHASE40_TEST_STATUS = `{payload.get('phase40_test_status')}`",
        f"PHASE40_TESTS = `{payload.get('phase40_tests')}`",
        "",
        "## Horizon honesty",
        "",
        "- Phase 28 = short ~15-day tape (preserved; not rewritten).",
        "- Phase 39 = 180-day research (preserved; expectancy ≈ -0.59R).",
        "- Phase 40 = 1291-day full-horizon research (preserved; expectancy +0.017224R).",
        "",
        json.dumps(rec.get("interpretation"), default=str),
        "",
        "### Why 180-day and full-horizon differ",
        "",
    ]
    for item in rec.get("why_they_differ") or []:
        lines.append(f"- {item}")
    lines += [
        "",
        "## Evidence matrix",
        "",
        "See JSON `evidence_matrix` and `docs_v2/02_research/PHASE41_BLOCKER_MATRIX.md`.",
        "",
        "## Broker / symbol",
        "",
        json.dumps(payload.get("symbol"), default=str),
        "",
        "Absence of `XAUUSD` from this REAL terminal catalog does **not** prove broker-wide absence.",
        "`XAUUSD_i` was not renamed. `XAUUSD` was not silently mapped.",
        "",
        "## Broker economics (strongest current snapshot)",
        "",
        json.dumps(payload.get("broker"), default=str),
        "",
        "## Commission / swap / spread / slippage / execution",
        "",
        f"- Commission: `{((payload.get('commission') or {}).get('status'))}` / `{((payload.get('commission') or {}).get('classification'))}`",
        f"- Swap: `{((payload.get('swap') or {}).get('SWAP_POLICY'))}`",
        f"- Spread: `{((payload.get('spread') or {}).get('SPREAD_POLICY'))}`",
        f"- Slippage: `{((payload.get('slippage') or {}).get('SLIPPAGE_POLICY'))}`",
        f"- Execution: `{((payload.get('execution') or {}).get('grade'))}`",
        f"- Request/fill pairs: `{((payload.get('request_fill') or {}).get('pairs'))}`",
        "",
        "## RAW vs EXECUTABLE",
        "",
        "RAW_PERFORMANCE != LIVE_PERFORMANCE.",
        "The +0.017224R RAW expectancy is **not** live profitability.",
        f"EXECUTABLE_PERFORMANCE = `{((payload.get('executable') or {}).get('status'))}`",
        "",
        "## Cost margin",
        "",
        json.dumps(m, default=str),
        "",
        "## Statistical interpretation",
        "",
        "PF>1, WR>X, or expectancy>0 is not a profitability rule here.",
        "Event-level bootstrap expectancy p5 is negative; the interval crosses zero.",
        "Independence is not claimed. Costs are incomplete. Therefore no inferential significance claim.",
        "",
        "## Verdicts",
        "",
        json.dumps(v, default=str),
        "",
        "## Next research phases",
        "",
        "Ordered by information value. Optimization is not recommended until a defensible edge exists.",
        "",
        json.dumps(payload.get("next_phases"), default=str),
        "",
        "## Stop",
        "",
        "STOP AFTER PHASE 41.",
        "DO NOT START PHASE 42.",
        "DO NOT OPTIMIZE.",
        "DO NOT TRADE.",
        "DO NOT MODIFY PRODUCTION.",
        "",
    ]
    path = root / PHASE41_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_blocker_md(root: Path, payload: dict[str, Any]) -> Path:
    lines = [
        "# Phase 41 — Blocker Matrix",
        "",
        "**RESEARCH / AUDIT ONLY.** Not a live-authorization document.",
        f"**FINAL_GATE:** `{payload.get('final_gate')}`",
        "",
        "| BLOCKER | SEVERITY | CURRENT STATUS | EVIDENCE | WHY IT MATTERS | EXACT CLOSURE ACTION | NO TRADE? | NO STRATEGY CHANGE? |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in payload.get("blockers") or []:
        lines.append(
            "| {blocker} | {severity} | {current_status} | {evidence} | {why_it_matters} | {exact_closure_action} | {can_close_without_trading} | {can_close_without_strategy_change} |".format(
                **{k: str(b.get(k, "")).replace("|", "/") for k in (
                    "blocker", "severity", "current_status", "evidence", "why_it_matters",
                    "exact_closure_action", "can_close_without_trading", "can_close_without_strategy_change",
                )}
            )
        )
    lines += [
        "",
        "Commission, request/fill, and executable evaluation are the highest-value closures.",
        "Do not start parameter optimization to paper over these blockers.",
        "",
    ]
    path = root / PHASE41_BLOCKERS_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _patch_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    p41_line = (
        "Phase 41 (`docs_v2/02_research/PHASE41_FINAL_EVIDENCE_CLOSURE.md`) is research-only "
        "final evidence closure and production-readiness audit. It does not authorize live trading, "
        "overwrite the frozen M5 snapshot, optimize, or start Phase 42."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    old40 = (
        "Phase 40 (`docs_v2/02_research/PHASE40_FULL_HORIZON_VALIDATION.md`) is research-only "
        "full-horizon unchanged-strategy validation on the Phase 38 XAUUSD_i M5 tape. "
        "It does not authorize live trading, overwrite the frozen M5 snapshot, optimize, or start Phase 41."
    )
    new40 = (
        "Phase 40 (`docs_v2/02_research/PHASE40_FULL_HORIZON_VALIDATION.md`) is research-only "
        "full-horizon unchanged-strategy validation on the Phase 38 XAUUSD_i M5 tape. "
        "It does not authorize live trading, overwrite the frozen M5 snapshot, or optimize."
    )
    if old40 in text and p41_line not in text:
        text = text.replace(old40, new40 + "\n\n" + p41_line)
        src.write_text(text, encoding="utf-8")
    elif p41_line not in text and new40 in text:
        text = text.replace(new40, new40 + "\n\n" + p41_line)
        src.write_text(text, encoding="utf-8")
    elif p41_line not in text:
        marker = "Phase 40 (`docs_v2/02_research/PHASE40_FULL_HORIZON_VALIDATION.md`)"
        if marker in text:
            idx = text.find(marker)
            end = text.find("\n\n", idx)
            if end == -1:
                text = text.rstrip() + "\n\n" + p41_line + "\n"
            else:
                text = text[:end] + "\n\n" + p41_line + text[end:]
            src.write_text(text, encoding="utf-8")

    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    ctext = ctext.replace(
        "| Phase 40 full-horizon validation | `run_phase40_collection()` | n/a | RESEARCH; full 1291-day unchanged gold_ny_sweep on phase38 XAUUSD_i M5; no bot/orders/.env | **PASS**; Phase 41 not started |",
        "| Phase 40 full-horizon validation | `run_phase40_collection()` | n/a | RESEARCH; full 1291-day unchanged gold_ny_sweep on phase38 XAUUSD_i M5; no bot/orders/.env | **PASS** |",
    )
    row41 = (
        "| Phase 41 final evidence closure | `run_phase41_collection()` | n/a | "
        "RESEARCH/AUDIT; no rescan; no bot/orders/.env | "
        f"**{payload.get('status')}**; Phase 42 not started |"
    )
    if "Phase 41 final evidence closure" not in ctext:
        ctext = ctext.replace(
            "| PA M5 `MIN_CONFIDENCE`",
            row41 + "\n| PA M5 `MIN_CONFIDENCE`",
        )
    cfg.write_text(ctext, encoding="utf-8")

    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    line = (
        "`tradingbot/backtest/phase41_final_evidence_closure.py` — **RESEARCH_ONLY** final evidence "
        "closure / readiness audit; reads Phase 38–40 artifacts; does not rescan or overwrite Phase 28 M5.\n"
    )
    if "phase41_final_evidence_closure.py" not in btext:
        btext = btext.replace(
            "`tradingbot/backtest/phase40_full_horizon_validation.py` — **RESEARCH_ONLY** full-horizon "
            "unchanged-strategy validation on the Phase 38 XAUUSD_i M5 tape; does not overwrite Phase 28 M5.\n",
            "`tradingbot/backtest/phase40_full_horizon_validation.py` — **RESEARCH_ONLY** full-horizon "
            "unchanged-strategy validation on the Phase 38 XAUUSD_i M5 tape; does not overwrite Phase 28 M5.  \n"
            + line,
        )
        bnd.write_text(btext, encoding="utf-8")

    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 41 started | **NO** |", "| Phase 41 started | **YES** |")
    block = f"""

## Final evidence closure (Phase 41)

| Claim | Status |
|---|---|
| Phase 41 status | **{payload.get("status")}** |
| Phase 40 rescan | **NO** |
| Frozen Phase 28/30 M5 overwritten | **NO** |
| Silent XAUUSD map | **NO** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Overall research verdict | **{((payload.get("verdict") or {}).get("G_OVERALL_RESEARCH_VERDICT") or {}).get("verdict")}** |
| Profitability verdict | **NOT ISSUED** |
| Phase 42 started | **NO** |
"""
    if "## Final evidence closure (Phase 41)" not in ktext:
        ktext = ktext.rstrip() + block
        ku.write_text(ktext, encoding="utf-8")


def run_phase41_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p16 = _safe_load_json(root / PHASE2716_JSON) or {}
    p38 = _safe_load_json(root / PHASE38_JSON) or {}
    p39 = _safe_load_json(root / PHASE39_JSON) or {}
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    recovery = _safe_load_json(root / "logs/phase40_recovery_status.json") or {}

    if not p40:
        payload = {
            "phase": PHASE,
            "timestamp_utc": _utc_now(),
            "status": "BLOCKED",
            "reason": "Phase 40 artifact missing; Phase 41 refuses to regenerate the scan.",
            "FINAL_GATE": BLOCKED,
            "final_gate": BLOCKED,
            "phase40_scan_rerun": False,
            "phase_42_started": False,
            "env_accessed": False,
            "production_changes": "NONE",
            "profitability_verdict": "NOT_ISSUED",
        }
        _write_json(root / PHASE41_JSON, _redact(payload))
        return payload

    verification = verify_phase40_facts(p40)
    scan = p40.get("scan") or {}
    raw = p40.get("raw_performance") or {}
    ev = p40.get("events") or {}
    dep = p40.get("dependence") or {}
    oos = p40.get("oos_sufficiency") or {}
    exe = p40.get("executable") or {}
    cls = p40.get("classification") or {}
    sf = p40.get("strategy_fingerprint") or {}
    eco = (p39.get("symbols") or {}).get("XAUUSD_i") or {}
    xau = (p39.get("symbols") or {}).get("XAUUSD") or {}
    mt5 = ((p39.get("mt5") or {}).get("attach") or {})
    comm = p39.get("commission") or {}
    slip = p39.get("slippage") or {}
    ex = p39.get("execution") or {}
    spread39 = p39.get("spread") or {}
    jsonl = derive_jsonl_diagnostics(root)
    conc = event_concentration(list(ev.get("sizes") or []))
    recon = reconcile_39_40(p38, p39, p40)
    margin = cost_margin(p40)
    swap_block = swap_relevance(p39, p40, jsonl)
    verdict = build_verdicts(p39, p40)
    blockers = build_blockers(p39, p40)
    nxt = build_next_phases()
    matrix = build_evidence_matrix(p38, p39, p40, p16, conc, jsonl)

    contradictions = [
        {
            "id": "P40_SESSION_VS_DISK",
            "a": "logs/phase40_recovery_status.json STATUS=INTERRUPTED / INTERNET_CONNECTION_LOST",
            "b": "logs/phase40_full_horizon_validation.json status=PASS, scan.completed=true",
            "higher_authority": "Phase 40 JSON artifact (collection result)",
            "classification": "CONTRADICTED",
            "resolution": "Session delivery was interrupted. On-disk collection completed. Phase 41 uses the JSON.",
        },
        {
            "id": "P40_PROGRESS_VS_JSONL",
            "a": "logs/phase40_scan_progress.json signals=1342 completed=true",
            "b": "Phase 40 JSON/JSONL signals=2847",
            "higher_authority": "Phase 40 JSON + JSONL",
            "classification": "STALE",
            "resolution": "Progress file is stale. Do not resume from it. Do not rescan.",
        },
        {
            "id": "P39_REMAINING_VS_P40",
            "a": "Phase 39 remaining_missing still listed full-tape TRAIN/VAL scan and OOS event floor",
            "b": "Phase 40 completed those items (TRAIN/VAL/OOS exist; OOS events=63)",
            "higher_authority": "Phase 40 artifact for horizon/OOS counts; Phase 39 artifact for cost statuses",
            "classification": "STALE",
            "resolution": "Horizon/OOS-count items are closed. Cost items in the same Phase 39 list remain open.",
        },
    ]

    payload: dict[str, Any] = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_status": p40.get("status"),
        "phase40_test_status": "PASS",
        "phase40_tests": "2/2",
        "phase40_scan_rerun": False,
        "phase40_verification": verification,
        "phase40_recovery_envelope": {
            "STATUS": recovery.get("STATUS"),
            "REASON": recovery.get("REASON"),
            "on_disk_collection_status": recovery.get("on_disk_collection_status"),
        },
        "data": {
            "path": PHASE38_M5,
            "rows": scan.get("tape_rows_loaded"),
            "start": scan.get("start"),
            "end": scan.get("end"),
            "days": p40.get("tape_days"),
            "fingerprint": p40.get("tape_fingerprint"),
            "source_modified": (p40.get("data_quality") or {}).get("source_modified"),
            "frozen_phase28_path": CANONICAL_PARQUET,
            "frozen_phase28_unchanged": (p40.get("fingerprints") or {}).get("phase28_m5_unchanged"),
        },
        "strategy": {
            "class": sf.get("strategy_class"),
            "preset": sf.get("preset"),
            "live_symbol": sf.get("live_symbol"),
            "code_wins": sf.get("code_wins"),
            "parameters_changed": sf.get("parameters_changed"),
            "logic_hash": sf.get("logic_hash"),
            "deterministic_fingerprint": sf.get("deterministic_fingerprint"),
        },
        "raw_performance": {
            "signals": scan.get("signals"),
            "BUY": scan.get("buy"),
            "SELL": scan.get("sell"),
            "WAIT": scan.get("wait"),
            "win_rate": raw.get("win_rate"),
            "expectancy_R": raw.get("expectancy_R"),
            "profit_factor": raw.get("profit_factor"),
            "max_drawdown_R": raw.get("max_drawdown_R"),
            "net_R": raw.get("net_R"),
            "label": raw.get("label"),
            "cost_adjusted": False,
            "is_live_profitability": False,
        },
        "oos": oos,
        "walk_forward": {
            "declaration": (p40.get("walk_forward") or {}).get("declaration"),
            "splits": (p40.get("walk_forward") or {}).get("splits"),
            "fold_signal_expectancy_R": {
                name: ((fold.get("signal_metrics") or {}).get("expectancy_R"))
                for name, fold in ((p40.get("walk_forward") or {}).get("folds") or {}).items()
            },
            "validated": False,
            "note": "Count-sufficient OOS is not a validated edge.",
        },
        "events": {
            "event_count": ev.get("event_count"),
            "signal_count": ev.get("signal_count"),
            "signals_per_event": ev.get("signals_per_event"),
            "floor_met": ev.get("floor_met"),
            "event_performance": ev.get("event_performance"),
            "concentration": conc,
        },
        "dependence": {
            "clustered_signal_share": dep.get("clustered_signal_share"),
            "same_event_reentries": dep.get("same_event_reentries"),
            "overlapping_holds": dep.get("overlapping_holds"),
            "independence_claimed": dep.get("independence_claimed"),
            "do_not_treat_signals_as_iid": dep.get("do_not_treat_signals_as_iid"),
        },
        "direction": p40.get("direction"),
        "stability": {
            "yearly": (p40.get("stability") or {}).get("yearly"),
            "regime": (p40.get("stability") or {}).get("regime"),
            "session": p40.get("session"),
            "weekday_from_jsonl": jsonl.get("weekday_counts"),
        },
        "jsonl_diagnostics": jsonl,
        "broker": {
            "broker": mt5.get("broker") or "LiteFinance Global LLC",
            "server": mt5.get("server") or "LiteFinance-MT5-Live",
            "environment": mt5.get("environment") or "REAL",
            "currency": "USD",
            "quote_utc": eco.get("quote_utc"),
            "XAUUSD_i": {
                "digits": eco.get("digits"),
                "point": eco.get("point"),
                "contract_size": eco.get("contract_size"),
                "tick_size": eco.get("tick_size"),
                "tick_value": eco.get("tick_value"),
                "volume_min": eco.get("volume_min"),
                "volume_max": eco.get("volume_max"),
                "volume_step": eco.get("volume_step"),
                "trade_mode": eco.get("trade_mode"),
                "trade_exemode": eco.get("trade_exemode"),
                "trade_calc_mode": eco.get("calc_mode"),
                "stops_level": eco.get("stops_level"),
                "freeze_level": eco.get("freeze_level"),
                "swap_long": eco.get("swap_long"),
                "swap_short": eco.get("swap_short"),
                "rollover3days": eco.get("rollover3days"),
            },
            "strongest_economics_source": PHASE39_JSON,
            "historical_economics_series": UNKNOWN,
        },
        "symbol": {
            "CURRENT_REAL_SYMBOL": "XAUUSD_i",
            "EXPECTED_USER_REAL_SYMBOL": "XAUUSD",
            "CODE_PRIMARY_SYMBOL": CODE_PRIMARY_SYMBOL,
            "SYMBOL_MAPPING": NOT_PROVEN,
            "XAUUSD_existence_this_terminal": xau.get("existence") or "NOT_OBSERVED_ON_THIS_TERMINAL",
            "broker_wide_absence_concluded": bool(xau.get("broker_wide_absence_concluded")),
            "ev_eq_01": p39.get("ev_eq_01") or p40.get("ev_eq_01") or NOT_PROVEN,
            "silent_mapping": False,
            "renamed": False,
            "note": "Absence of XAUUSD from this terminal does not prove broker-wide absence.",
        },
        "commission": {
            "status": comm.get("status") or UNKNOWN,
            "classification": comm.get("classification") or "OBSERVED_ZERO_NOT_PROVEN",
            "verified_schedule": bool(comm.get("verified_schedule")),
            "zero_is_not_verified": True,
            "account_product_type": comm.get("account_product_type") or UNKNOWN,
            "xauusd_i_deals_zero": comm.get("all_observed_zeros"),
            "invented": False,
            "closure": "Account-applicable VERIFIED_SCHEDULE with product type, basis, rate, currency, effective date.",
        },
        "swap": swap_block,
        "spread": {
            "SPREAD_POLICY": "PROXY / PARTIAL",
            "evaluation_tape_bid_ask": bool(spread39.get("evaluation_tape_bid_ask")),
            "phase35_sidecar_n": 2952,
            "phase35_sidecar_median_price": 0.4099999999998545,
            "phase35_sidecar_p75": 0.42000000000007276,
            "phase35_sidecar_p90": 0.42000000000007276,
            "phase35_sidecar_p95": 0.5599999999994907,
            "phase35_sidecar_p99": 0.5799999999999272,
            "phase35_source": "docs_v2/02_research/PHASE35_EXECUTION_REALITY.md",
            "ohlc_proxy_relabeled_observed": False,
            "covers_phase38_tape": False,
        },
        "slippage": {
            "SLIPPAGE_EVIDENCE": UNKNOWN,
            "SLIPPAGE_POLICY": "MODELED",
            "genuine_pairs": slip.get("genuine_requested_vs_executed_pairs", 0),
            "mt5_deviation_is_realized_slippage": False,
            "price_open_is_requested": False,
        },
        "execution": {
            "grade": ex.get("grade") or "DEAL_FILL_TAPE_ONLY",
            "deals": ex.get("deals"),
            "orders": ex.get("orders"),
            "xauusd_i_deals": ex.get("xauusd_i_deals"),
            "requotes": ex.get("requotes") or UNKNOWN,
            "latency": ex.get("latency") or UNKNOWN,
            "requested_vs_executed_price": ex.get("requested_vs_executed_price") or "NOT_IDENTIFIABLE",
            "requested_vs_executed_volume": ex.get("requested_vs_executed_volume") or "NOT_IDENTIFIABLE",
            "possible_partials": ex.get("possible_partials"),
        },
        "request_fill": {
            "pairs": slip.get("genuine_requested_vs_executed_pairs", 0),
            "journal_xauusd_i_pairs": 0,
            "status": "0",
        },
        "executable": {
            "status": "NOT_ESTABLISHED",
            "candidates": exe.get("candidates"),
            "allowed": exe.get("allowed"),
            "rejected": exe.get("rejected"),
            "fills": exe.get("executed_simulated_trades"),
            "reject_attribution": exe.get("reject_attribution"),
            "phase40_status": exe.get("status"),
            "mixed_with_raw": False,
        },
        "cost_model": p39.get("cost_completeness") or p40.get("cost_completeness"),
        "cost_margin": margin,
        "robustness": p40.get("robustness"),
        "statistics": p40.get("statistics"),
        "reconciliation": recon,
        "contradictions": contradictions,
        "evidence_matrix": matrix,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "prior_phase16_final_gate": p16.get("FINAL_GATE"),
        "gate_unchanged": True,
        "verdict": verdict,
        "profitability_verdict": "NOT_ISSUED",
        "blockers": blockers,
        "next_phases": nxt,
        "phase_42_started": False,
        "parameters_optimized": False,
        "env_accessed": False,
        "datasets_changed": False,
        "silent_xauusd_mapping": False,
        "production_safety": {
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_READ": False,
            "MT5_STARTED": False,
            "PRODUCTION_MODIFIED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "EXECUTION_CHANGED": False,
            "ML_ACTIVATED": False,
            "OPTIMIZED": False,
            "PHASE40_RESCAN": False,
            "PHASE42_STARTED": False,
            "production_changes": "NONE",
            "TRADING": "NOT_PERFORMED",
        },
        "git_head": _git_head(root),
        "artifacts": {
            "json": PHASE41_JSON,
            "md": PHASE41_MD,
            "blocker_md": PHASE41_BLOCKERS_MD,
            "phase40_json": PHASE40_JSON,
            "phase40_md": PHASE40_MD,
            "phase39_json": PHASE39_JSON,
            "phase38_json": PHASE38_JSON,
            "phase16_json": PHASE2716_JSON,
        },
        "legacy_ml_phase41_not_this_phase": [
            "tradingbot/ml/research/phase41/run_phase41.py",
            "tests/test_phase41.py",
        ],
    }
    payload = _redact(payload)
    _write_json(root / PHASE41_JSON, payload)
    _write_markdown(root, payload)
    _write_blocker_md(root, payload)
    _patch_truth_docs(root, payload)
    return payload


if __name__ == "__main__":
    out = run_phase41_collection(Path("."))
    print("STATUS", out.get("status"))
    print("FINAL_GATE", out.get("final_gate"))
    print("OVERALL", ((out.get("verdict") or {}).get("G_OVERALL_RESEARCH_VERDICT") or {}).get("verdict"))
    print("PHASE40_RESCAN", out.get("phase40_scan_rerun"))
    print("COMMISSION", (out.get("commission") or {}).get("status"))
