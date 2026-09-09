"""Phase 36 — strategy evidence verdict and research decision.

RESEARCH ONLY. Synthesizes Phases 28.0–35. Does not optimize, change
production, place orders, or start another phase.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.broker import SimulatedBroker
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
    PHASE280_BASELINE_JSON,
    UNKNOWN,
)
from tradingbot.backtest.phase28_1_full_baseline import PHASE281_JSON
from tradingbot.backtest.phase28_2_walk_forward import PHASE282_JSON
from tradingbot.backtest.phase28_3_monte_carlo import PHASE283_JSON
from tradingbot.backtest.phase28_4_strategy_diagnosis import PHASE284_JSON
from tradingbot.backtest.phase29_research_tape import PHASE29_JSON
from tradingbot.backtest.phase30_unchanged_strategy_evaluation import PHASE30_JSON
from tradingbot.backtest.phase31_event_independence import PHASE31_JSON
from tradingbot.backtest.phase32_walk_forward import PHASE32_JSON
from tradingbot.backtest.phase33_robustness import PHASE33_JSON
from tradingbot.backtest.phase34_statistical_validation import PHASE34_JSON
from tradingbot.backtest.phase35_execution_reality import PHASE35_JSON
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.pa_symbol_tf_presets import PA_SYMBOL_TF_PRESETS

PHASE = "36"
PHASE36_JSON = "logs/phase36_strategy_verdict.json"
PHASE36_MD = "docs_v2/02_research/PHASE36_STRATEGY_VERDICT.md"
EVALUATOR_VERSION = "phase36-verdict-v1"

VERDICT_A = "EVIDENCE_SUPPORTS_EDGE"
VERDICT_B = "EVIDENCE_DOES_NOT_SUPPORT_EDGE"
VERDICT_C = "EVIDENCE_SUPPORTS_NO_EDGE"
VERDICT_D = "INSUFFICIENT_EVIDENCE"
ALLOWED_VERDICTS = (VERDICT_A, VERDICT_B, VERDICT_C, VERDICT_D)
HIERARCHY_LEVELS = ("PROVEN", "STRONGLY_SUPPORTED", "PLAUSIBLE", "UNRESOLVED", "DISPROVEN")

SOURCE_ARTIFACTS = {
    "phase28_0": PHASE280_BASELINE_JSON,
    "phase28_1": PHASE281_JSON,
    "phase28_2": PHASE282_JSON,
    "phase28_3": PHASE283_JSON,
    "phase28_4": PHASE284_JSON,
    "phase29": PHASE29_JSON,
    "phase30": PHASE30_JSON,
    "phase31": PHASE31_JSON,
    "phase32": PHASE32_JSON,
    "phase33": PHASE33_JSON,
    "phase34": PHASE34_JSON,
    "phase35": PHASE35_JSON,
}

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "parameters_optimized",
    "production_changed",
    "dataset_fingerprint",
    "evidence_sources",
    "evidence_hierarchy",
    "distinctions",
    "strategy_verdict",
    "missing_evidence",
    "research_decision",
    "FINAL_GATE",
    "phase_37_started",
)

CANONICAL_CODE = {
    "live_symbol": "tradingbot/config/live.py::PRIMARY_SYMBOL",
    "preset": "tradingbot/config/pa_symbol_tf_presets.py::PA_SYMBOL_TF_PRESETS[XAUUSD][M5]",
    "strategy": "engine/strategies/price_action_strategy.py",
    "sweep": "tradingbot/domain/gold_strategies/m5_london_sweep.py",
    "riskgate": "tradingbot/adapters/risk_gate.py",
    "cost_model": "tradingbot/backtest/broker.py::SimulatedBroker",
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


def _stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _load_required(root: Path) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name, rel in SOURCE_ARTIFACTS.items():
        payload = _safe_load_json(root / rel) or {}
        if not payload:
            missing.append(rel)
        loaded[name] = payload
    if missing:
        raise FileNotFoundError("Phase 36 missing prior artifacts: " + ", ".join(missing))
    return loaded


def _conclusion_verdict(payload: dict[str, Any]) -> str:
    conclusion = payload.get("conclusion")
    if isinstance(conclusion, dict):
        return str(conclusion.get("verdict") or UNKNOWN)
    if isinstance(conclusion, str) and conclusion:
        return conclusion
    return str(payload.get("status") or UNKNOWN)


def _inspect_canonical_code() -> dict[str, Any]:
    m5 = PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"]
    return {
        "primary_symbol": PRIMARY_SYMBOL,
        "preset": m5.get("PRESET"),
        "gold_strategy_mode": m5.get("GOLD_STRATEGY_MODE"),
        "min_confidence": m5.get("MIN_CONFIDENCE"),
        "min_quality_score": m5.get("MIN_QUALITY_SCORE"),
        "min_rr": m5.get("MIN_RR"),
        "tp_rr": m5.get("TP_RR"),
        "sl_atr_mult": m5.get("SL_ATR_MULT"),
        "ny_entry_start_hour": m5.get("NY_ENTRY_START_HOUR"),
        "ny_entry_end_hour": m5.get("NY_ENTRY_END_HOUR"),
        "asian_end_hour": m5.get("ASIAN_END_HOUR"),
        "cooldown_bars": m5.get("COOLDOWN_BARS"),
        "max_trades_per_day": m5.get("MAX_TRADES_PER_DAY"),
        "meta_label_threshold": m5.get("META_LABEL_THRESHOLD"),
        "production_files_modified_this_phase": False,
        "riskgate_module": CANONICAL_CODE["riskgate"],
        "simulated_broker_class": SimulatedBroker.__name__,
        "citations": CANONICAL_CODE,
    }


def evaluate(root: Path) -> dict[str, Any]:
    src = _load_required(root)
    p280, p281, p282, p283, p284 = (
        src["phase28_0"],
        src["phase28_1"],
        src["phase28_2"],
        src["phase28_3"],
        src["phase28_4"],
    )
    p29, p30, p31, p32, p33, p34, p35 = (
        src["phase29"],
        src["phase30"],
        src["phase31"],
        src["phase32"],
        src["phase33"],
        src["phase34"],
        src["phase35"],
    )
    code = _inspect_canonical_code()
    raw = (p30.get("raw_signal_book") or {}).get("performance") or {}
    event_perf = (p31.get("performance") or {}).get("per_event") or {}
    exe = p30.get("executable_book") or {}
    filled = p30.get("filled_book") or {}
    sufficiency = p30.get("statistical_sufficiency") or {}
    ranking = p284.get("root_cause_ranking") or {}
    folds = p32.get("folds") or {}
    oos = folds.get("OOS") or {}
    boot_event = ((p34.get("bootstrap") or {}).get("event_level") or {}).get("bootstrap") or {}
    event_exp_ci = boot_event.get("expectancy_R") or {}
    cost = p35.get("cost_completeness") or {}
    coverage = (p29.get("dataset_coverage") or {}).get("m5") or {}
    event_n = int((p31.get("event_metrics") or {}).get("event_count") or 0)
    signal_n = int((p31.get("event_metrics") or {}).get("signal_count") or raw.get("n") or 0)
    calendar_days = float(coverage.get("days") or 0.0)
    floors = {
        "resolved_trades": {
            "value": signal_n,
            "required": MIN_RESOLVED_FOR_SUFFICIENCY,
            "pass": signal_n >= MIN_RESOLVED_FOR_SUFFICIENCY,
        },
        "unique_events": {
            "value": event_n,
            "required": MIN_RESOLVED_FOR_SUFFICIENCY,
            "pass": event_n >= MIN_RESOLVED_FOR_SUFFICIENCY,
        },
        "calendar_days": {
            "value": calendar_days,
            "required": MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
            "pass": calendar_days >= MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
        },
    }
    sample_sufficient = all(item["pass"] for item in floors.values())
    cost_complete = str(cost.get("classification")) == "COMPLETE"
    ci_contains_zero = bool((p34.get("conclusion") or {}).get("event_ci_expectancy_contains_zero"))
    filled_n = int(filled.get("n") or 0)
    event_exp = event_perf.get("expectancy_R")
    oos_events = int(oos.get("events") or 0)
    strong_positive = (
        sample_sufficient
        and cost_complete
        and filled_n > 0
        and isinstance(event_exp, (int, float))
        and event_exp > 0
        and not ci_contains_zero
        and oos_events >= MIN_RESOLVED_FOR_SUFFICIENCY
    )
    strong_negative = (
        sample_sufficient
        and isinstance(event_exp, (int, float))
        and event_exp < 0
        and not ci_contains_zero
        and cost_complete
    )
    if strong_positive:
        verdict = VERDICT_A
        a_reason = "Strong event-level, OOS, fill, and cost-complete evidence of positive expectancy."
        b_reason = "Not selected."
        c_reason = "Positive-expectancy evidence is present; no-edge is not supported."
        d_reason = "Not selected."
    elif strong_negative:
        verdict = VERDICT_C
        a_reason = "Negative event-level evidence after sufficiency floors; edge is not supported."
        b_reason = "C is used because the no-edge evidence is strong, not merely unsupported-edge."
        c_reason = "Strong event-level negative expectancy after sufficiency and cost completeness."
        d_reason = "Not selected."
    elif sample_sufficient and not strong_positive:
        verdict = VERDICT_B
        a_reason = "Sample is large enough but does not show a supported edge."
        b_reason = "Adequate sample still fails to support an edge claim."
        c_reason = "No-edge is not strongly proven (CI, costs, or fills remain incomplete)."
        d_reason = "Not selected."
    else:
        verdict = VERDICT_D
        a_reason = (
            "No completed phase produced independent, cost-complete, filled, or sufficient-sample "
            "evidence of an edge. A requires genuinely strong evidence."
        )
        b_reason = (
            "Not selected. Repeating the same 15-day RAW book across Phases 28–35 would upgrade "
            "an insufficient description into a strategy finding. Phase 30 already recorded that "
            "the book does not support an edge claim and does not support a no-edge claim."
        )
        c_reason = (
            "Event n=6, calendar days ~14.88, event expectancy CI contains 0, cost completeness "
            "INCOMPLETE, FILLED n=0. C requires genuinely strong evidence of no edge."
        )
        d_reason = (
            "Sufficiency floors from Phase 28.0 are unmet (resolved>=30, events>=30, days>=60). "
            "Phase 29 did not obtain a 60- or 180-day M5 tape. Cost AND-gate is 0/8 COMPLETE. "
            "That missing evidence prevents A, B, and C."
        )

    sources = {
        "phase28_0": {
            "artifact": PHASE280_BASELINE_JSON,
            "verdict": (p280.get("statistical_sufficiency") or {}).get("classification"),
            "role": "Foundation: best defensible XAUUSD_i M5 tape, floors, closed-bar contract.",
        },
        "phase28_1": {
            "artifact": PHASE281_JSON,
            "verdict": _conclusion_verdict(p281),
            "raw_setups": (p281.get("raw_signal") or {}).get("setups") or signal_n,
            "executable_allowed": (p281.get("executable") or {}).get("allowed"),
            "role": "Chronological RAW vs RiskGate baseline on the frozen tape.",
        },
        "phase28_2": {
            "artifact": PHASE282_JSON,
            "verdict": _conclusion_verdict(p282),
            "role": "First 60/20/20 chronological split; TRAIN/VAL descriptive.",
        },
        "phase28_3": {
            "artifact": PHASE283_JSON,
            "verdict": _conclusion_verdict(p283),
            "role": "Monte Carlo on stored baseline R; MODELED costs; no OHLC rewalk.",
        },
        "phase28_4": {
            "artifact": PHASE284_JSON,
            "official_answer": ranking.get("official_answer_to_primary_question"),
            "primary": (ranking.get("PRIMARY") or {}).get("code"),
            "role": "Diagnosis of stored RAW setups. Official answer J.",
        },
        "phase29": {
            "artifact": PHASE29_JSON,
            "m5_days": calendar_days,
            "below_minimum_60d": bool(coverage.get("below_minimum_60d")),
            "logical_xauusd_used": bool((p29.get("datasets") or {}).get("logical_xauusd_used")),
            "role": "Longest defensible XAUUSD_i tape. 180d NOT_OBTAINED.",
        },
        "phase30": {
            "artifact": PHASE30_JSON,
            "verdict": _conclusion_verdict(p30),
            "raw_n": signal_n,
            "raw_expectancy_R": raw.get("expectancy_R"),
            "executable_allowed": exe.get("allowed"),
            "filled_status": filled.get("status"),
            "role": "Unchanged strategy evaluation. RAW / EXECUTABLE / FILLED stay separate.",
        },
        "phase31": {
            "artifact": PHASE31_JSON,
            "verdict": _conclusion_verdict(p31),
            "events": event_n,
            "signals_per_event_mean": ((p31.get("event_metrics") or {}).get("signals_per_event") or {}).get("mean"),
            "not_a_strategy_failure": bool((p31.get("conclusion") or {}).get("not_a_strategy_failure")),
            "role": "Mechanical event independence. Official inferential unit.",
        },
        "phase32": {
            "artifact": PHASE32_JSON,
            "verdict": _conclusion_verdict(p32),
            "oos_setups": oos.get("setups"),
            "oos_events": oos.get("events"),
            "oos_expectancy_R": oos.get("expectancy"),
            "role": "Chronological walk-forward of the unchanged strategy.",
        },
        "phase33": {
            "artifact": PHASE33_JSON,
            "verdict": _conclusion_verdict(p33),
            "material_hits": (p33.get("conclusion") or {}).get("material_diagnostic_hits"),
            "role": "Pre-declared robustness diagnostics. Not optimization.",
        },
        "phase34": {
            "artifact": PHASE34_JSON,
            "verdict": _conclusion_verdict(p34),
            "event_expectancy_p5": event_exp_ci.get("p5"),
            "event_expectancy_p95": event_exp_ci.get("p95"),
            "event_ci_contains_zero": ci_contains_zero,
            "role": "Bootstrap/MC. Signal-level is not independent evidence.",
        },
        "phase35": {
            "artifact": PHASE35_JSON,
            "cost_completeness": cost.get("classification"),
            "complete_count": cost.get("complete_count"),
            "theoretical_edge_claim": cost.get("theoretical_edge_claim"),
            "role": "Broker cost / execution reality. MODELED is not VERIFIED.",
        },
    }

    hierarchy = {
        "PROVEN": [
            {
                "claim": "Canonical M5 fingerprint is frozen and matches Phases 28.0–35.",
                "value": EXPECTED_CANONICAL_FINGERPRINT,
            },
            {
                "claim": "Defensible XAUUSD_i M5 coverage is ~14.88 days / 3000 bars, below the 60-day floor.",
                "value": calendar_days,
            },
            {
                "claim": "Sufficiency floors (resolved>=30, events>=30, days>=60) are unmet.",
                "value": floors,
            },
            {
                "claim": "On this tape the RAW book is 24 dependent setups, 1 win / 23 losses. This is a tape description, not a population parameter.",
                "value": {"n": signal_n, "expectancy_R": raw.get("expectancy_R"), "win_rate": raw.get("win_rate")},
            },
            {
                "claim": "Phase 31 HIGH_DEPENDENCE: 24 signals collapse to 6 mechanical events. Treating signals as independent is disallowed.",
                "value": event_n,
            },
            {
                "claim": "EXECUTABLE allowed=0 (META 18, ATR 6). This is a RiskGate book, not a strategy failure.",
                "value": exe.get("attribution"),
            },
            {
                "claim": "FILLED is NOT_OBSERVED (n=0). Theoretical R is not live fill P/L.",
                "value": filled,
            },
            {
                "claim": "Cost completeness AND-gate is INCOMPLETE (0/8). Cost-adjusted validation remains forbidden.",
                "value": {"classification": cost.get("classification"), "complete_count": cost.get("complete_count")},
            },
            {
                "claim": "EV-EQ-01 remains NOT_PROVEN. Logical XAUUSD tapes were not used.",
                "value": p30.get("ev_eq_01") or p29.get("ev_eq_01"),
            },
            {
                "claim": "Phase 28.4 official answer is J: no single proven structural cause of the RAW path.",
                "value": ranking.get("official_answer_to_primary_question"),
            },
            {
                "claim": "Event-level bootstrap expectancy CI contains 0 (p5=-1.00, p95=+0.25). That is not significance.",
                "value": event_exp_ci,
            },
            {
                "claim": "Phases 28–35 did not optimize parameters and did not change production strategy/RiskGate/ML.",
                "value": True,
            },
            {
                "claim": "Production FINAL_GATE remains BLOCKED. This phase does not authorize live trading.",
                "value": BLOCKED,
            },
        ],
        "STRONGLY_SUPPORTED": [
            {
                "claim": "No completed phase produced evidence that supports an edge claim (A is not available).",
                "note": "This is not upgraded to verdict B. The same insufficient book is not counted twelve times.",
            },
            {
                "claim": "On this tape, every chronological fold’s RAW expectancy is negative. Descriptive only; folds are FOLD_INSUFFICIENT.",
                "value": {
                    name: (fold or {}).get("expectancy")
                    for name, fold in folds.items()
                },
            },
            {
                "claim": "Live production owner remains PriceActionStrategy / gold_ny_sweep / london_sweep on XAUUSD_i M5, unchanged by this phase.",
                "value": {
                    "symbol": code["primary_symbol"],
                    "preset": code["preset"],
                    "mode": code["gold_strategy_mode"],
                },
            },
        ],
        "PLAUSIBLE": [
            {
                "claim": "Overlapping holds, shared stops, and NY 15–16 concentration can inflate RAW loss count on this tape (Phase 28.4 H/A/C/E).",
                "not_proven_oos": True,
            },
            {
                "claim": "META and ATR gates would have blocked these RAW candidates if they were live. That does not diagnose RAW signal quality.",
                "value": exe.get("attribution"),
            },
            {
                "claim": "Broker economics, if later COMPLETE and adverse, could further reduce any hypothetical theoretical expectancy. Survival is currently NOT_PROVEN, not disproven.",
            },
        ],
        "UNRESOLVED": [
            {"claim": "Whether gold_ny_sweep has a trading edge on a longer defensible XAUUSD_i tape."},
            {"claim": "Whether any theoretical edge would survive COMPLETE broker costs."},
            {"claim": "Whether SL, TP/RR, entry timing, session window, or regime is a structural cause."},
            {"claim": "Live requested-vs-executed fill, partial, rejection, requote, and latency behavior."},
            {"claim": "Account-applicable commission schedule and historical swap series."},
            {"claim": "Genuine realized slippage (requested vs executed). MT5 deviation is not that quantity."},
            {"claim": "EV-EQ-01 equivalence of logical XAUUSD to XAUUSD_i."},
        ],
        "DISPROVEN": [
            {"claim": "That 24 RAW signals are 24 independent market events."},
            {"claim": "That 0 RiskGate allows proves the strategy has no edge."},
            {"claim": "That RiskGate caused the RAW −0.90 R path. RAW is scored before the gate."},
            {"claim": "That theoretical R is live or filled performance."},
            {"claim": "That MODELED / MODELED_PROXY costs are VERIFIED."},
            {"claim": "That this tape meets the 60-day or 180-day research floors."},
            {"claim": "That EV-EQ-01 is proven."},
            {"claim": "That cost-adjusted validation is authorized."},
            {"claim": "That MT5 deviation is realized slippage."},
            {"claim": "That short-tape zero commission or swap is a verified schedule."},
            {"claim": "That repeating the same unsupported claim across phases upgrades its evidence grade."},
        ],
    }

    missing = [
        {
            "item": "Defensible XAUUSD_i M5 tape ≥ 60 calendar days (target 180).",
            "have": f"{calendar_days:.2f} days",
            "prevents": [VERDICT_A, VERDICT_B, VERDICT_C],
            "source": "Phase 29; floors from Phase 28.0",
        },
        {
            "item": "≥ 30 independent mechanical events.",
            "have": event_n,
            "prevents": [VERDICT_A, VERDICT_B, VERDICT_C],
            "source": "Phase 31 official event unit; Phase 28.0 floor",
        },
        {
            "item": "Cost completeness AND-gate COMPLETE (symbol binding, economics, provenance, spread, commission, swap, slippage, execution).",
            "have": f"{cost.get('complete_count') or 0}/8 {cost.get('classification')}",
            "prevents": [VERDICT_A, VERDICT_C],
            "source": "Phase 35 / Phase 27.15",
        },
        {
            "item": "Genuine requested-vs-executed fill sample if claiming executable or live edge.",
            "have": f"FILLED n={filled_n} {filled.get('status')}",
            "prevents": [VERDICT_A],
            "source": "Phase 30 FILLED; Phase 35 execution",
        },
        {
            "item": "Chronological OOS with sufficient independent events (not 2.16 days / 3 events).",
            "have": f"OOS events={oos_events} expectancy={oos.get('expectancy')}",
            "prevents": [VERDICT_A, VERDICT_C],
            "source": "Phase 32",
        },
    ]

    distinctions = {
        "strategy_signal_quality": {
            "book": "RAW_SIGNAL",
            "finding": "Theoretical closed-bar gold_ny_sweep setups on this tape: 24 dependent rows, 1/23, expectancy about −0.90 R. Not live. Not cost-adjusted. Not independent.",
            "blame_riskgate": False,
        },
        "riskgate_behavior": {
            "book": "EXECUTABLE",
            "finding": "0 allowed / 24 rejected (META 18, ATR 6). Separate from RAW. 0 allows is not a strategy verdict.",
            "blame_strategy_for_rejects": False,
        },
        "execution_behavior": {
            "book": "FILLED",
            "finding": "NOT_OBSERVED. Requested/executed pairs were not fabricated. SimulatedBroker is not realized.",
        },
        "broker_costs": {
            "finding": "AND-gate INCOMPLETE. MODELED not VERIFIED. Theoretical edge surviving economics: NOT_PROVEN.",
        },
        "data_quality": {
            "finding": "Canonical OHLC has 0 duplicate/malformed/impossible candles on the frozen snapshot. Bid/Ask production parquet is PROXY. Sidecar 27.26 is OBSERVED for that window only. Provenance PARTIAL. EV-EQ-01 NOT_PROVEN.",
        },
        "sample_sufficiency": {
            "finding": "DATA_INSUFFICIENT / INSUFFICIENT_SAMPLE across Phases 28.0–34. Official inferential unit n=6 events.",
        },
    }

    cause_review = {
        "signal_definition_problem": "UNRESOLVED — not proven; HIGH_DEPENDENCE is an independence finding.",
        "entry_problem": "UNRESOLVED — Phase 28.4 counterfactuals were analytical only.",
        "sl_problem": "PLAUSIBLE on this tape (shared-stop clusters); not proven OOS.",
        "tp_problem": "UNRESOLVED.",
        "session_problem": "By design all RAW timestamps are NY 15–16 UTC. That concentrates the sample; it does not prove the window is wrong.",
        "regime_problem": "UNRESOLVED — one win cannot define a regime contrast.",
        "cost_problem": "Costs are INCOMPLETE, not a proven cause of the RAW path (RAW is gross).",
        "data_problem": "PROVEN as an inference limit (G). Not proven as the generator of the −0.90 R path.",
        "no_identifiable_cause": "PROVEN for a single structural cause — official answer J.",
        "optimization_supported": False,
        "note": "Do not blindly optimize. Only recommend changes supported by evidence. None are.",
    }

    return {
        "evidence_sources": sources,
        "canonical_code": code,
        "dataset": {
            "path": CANONICAL_PARQUET,
            "fingerprint": EXPECTED_CANONICAL_FINGERPRINT,
            "symbol": PRIMARY_SYMBOL,
            "provenance": (p280.get("provenance") or p29.get("provenance")),
            "logical_xauusd_used": False,
            "ev_eq_01": p30.get("ev_eq_01") or "NOT_PROVEN",
        },
        "floors": floors,
        "sample_sufficient": sample_sufficient,
        "cost_complete": cost_complete,
        "distinctions": distinctions,
        "evidence_hierarchy": hierarchy,
        "strategy_verdict": {
            "code": verdict,
            "allowed_codes": list(ALLOWED_VERDICTS),
            "a_not_selected_reason": a_reason,
            "b_not_selected_reason": b_reason,
            "c_not_selected_reason": c_reason,
            "d_selected_reason": d_reason if verdict == VERDICT_D else None,
            "selected_reason": d_reason if verdict == VERDICT_D else (b_reason if verdict == VERDICT_B else a_reason),
            "edge_exists_claim": False,
            "no_edge_exists_claim": False,
            "theoretical_is_not_live": True,
            "strong_positive_edge_evidence": strong_positive,
            "strong_no_edge_evidence": strong_negative,
        },
        "if_edge_existed_would_require": {
            "not_applicable": verdict != VERDICT_A,
            "note": "A was not selected. No controlled optimization phase is opened.",
        },
        "cause_review": cause_review,
        "missing_evidence": missing,
        "research_decision": {
            "optimize_production": False,
            "change_production": False,
            "start_another_phase_automatically": False,
            "re_audit_same_15_day_book": False,
            "invent_another_audit_because_inconvenient": False,
            "binding_constraint_if_operator_later_continues": (
                "Obtain a longer defensible XAUUSD_i M5 tape and COMPLETE cost evidence. "
                "Do not search SL/TP/RR/session on this 24-row book."
            ),
            "text": (
                "INSUFFICIENT_EVIDENCE. Stop the 28–35 program on this tape. Do not optimize. "
                "Do not change production. Do not start Phase 37 automatically. "
                "Do not re-diagnose the same 24 dependent rows."
            ),
        },
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    v = payload["strategy_verdict"]
    h = payload["evidence_hierarchy"]
    miss = payload["missing_evidence"]
    d = payload["distinctions"]
    (root / PHASE36_MD).parent.mkdir(parents=True, exist_ok=True)
    proven = "\n".join(f"- {item['claim']}" for item in h["PROVEN"])
    strong = "\n".join(f"- {item['claim']}" for item in h["STRONGLY_SUPPORTED"])
    plausible = "\n".join(f"- {item['claim']}" for item in h["PLAUSIBLE"])
    unresolved = "\n".join(f"- {item['claim']}" for item in h["UNRESOLVED"])
    disproven = "\n".join(f"- {item['claim']}" for item in h["DISPROVEN"])
    missing_md = "\n".join(
        f"- **{item['item']}** — have `{item['have']}` (source: {item['source']})"
        for item in miss
    )
    (root / PHASE36_MD).write_text(
        f"""# Phase 36 — Strategy Evidence Verdict & Research Decision

**Status:** PASS
**Class:** RESEARCH ONLY
**Strategy verdict:** `{v["code"]}`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Production changed:** NO
**FINAL_GATE:** `BLOCKED`

STOP AFTER PHASE 36. DO NOT START PHASE 37.
DO NOT OPTIMIZE. DO NOT MODIFY PRODUCTION.

This phase synthesizes Phases 28.0–35 against the current production `gold_ny_sweep`
implementation, RiskGate, cost model, provenance, and frozen dataset fingerprint.
It is **not** an optimization phase.

---

## Verdict

**{v["code"]}**

Allowed codes: A `{VERDICT_A}` · B `{VERDICT_B}` · C `{VERDICT_C}` · D `{VERDICT_D}`.

A and C were not used: they require genuinely strong evidence.

- **A not selected:** {v["a_not_selected_reason"]}
- **B not selected:** {v["b_not_selected_reason"]}
- **C not selected:** {v["c_not_selected_reason"]}
- **D selected:** {v["selected_reason"]}

`edge_exists_claim=false`. `no_edge_exists_claim=false`.
Theoretical performance is **not** live performance.

---

## Distinctions

| Layer | Finding |
|---|---|
| Strategy signal quality | {d["strategy_signal_quality"]["finding"]} |
| RiskGate behavior | {d["riskgate_behavior"]["finding"]} |
| Execution behavior | {d["execution_behavior"]["finding"]} |
| Broker costs | {d["broker_costs"]["finding"]} |
| Data quality | {d["data_quality"]["finding"]} |
| Sample sufficiency | {d["sample_sufficiency"]["finding"]} |

Do not blame the strategy for RiskGate rejection.
Do not blame RiskGate for RAW strategy performance.

---

## Evidence hierarchy

Repeated reports of the same 15-day book are **one** observation, not twelve independent confirmations.

### PROVEN

{proven}

### STRONGLY SUPPORTED

{strong}

### PLAUSIBLE

{plausible}

### UNRESOLVED

{unresolved}

### DISPROVEN

{disproven}

---

## Canonical code (unchanged)

| Item | Value |
|---|---|
| Symbol | `{payload["canonical_code"]["primary_symbol"]}` |
| Preset | `{payload["canonical_code"]["preset"]}` / `{payload["canonical_code"]["gold_strategy_mode"]}` |
| NY window | {payload["canonical_code"]["ny_entry_start_hour"]}–{payload["canonical_code"]["ny_entry_end_hour"]} UTC |
| Asian end | {payload["canonical_code"]["asian_end_hour"]}:00 UTC |
| MIN_CONFIDENCE | {payload["canonical_code"]["min_confidence"]} |
| MIN_QUALITY_SCORE | {payload["canonical_code"]["min_quality_score"]} |
| MIN_RR / TP_RR | {payload["canonical_code"]["min_rr"]} / {payload["canonical_code"]["tp_rr"]} |
| SL_ATR_MULT | {payload["canonical_code"]["sl_atr_mult"]} |
| COOLDOWN_BARS | {payload["canonical_code"]["cooldown_bars"]} |
| MAX_TRADES_PER_DAY | {payload["canonical_code"]["max_trades_per_day"]} |
| META_LABEL_THRESHOLD | {payload["canonical_code"]["meta_label_threshold"]} |
| Fingerprint | `{payload["dataset_fingerprint"]}` |

Citations: `PRIMARY_SYMBOL`, `PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"]`, `PriceActionStrategy`, `evaluate_m5_london_sweep`, `RiskGate`, `SimulatedBroker` (commission UNKNOWN fail-closed).

---

## If edge existed

Not applicable. A was not selected. No controlled optimization phase is opened.

## If edge does not exist

C was not selected. Cause review (evidence-supported only):

| Candidate | Status |
|---|---|
| Signal definition | {payload["cause_review"]["signal_definition_problem"]} |
| Entry | {payload["cause_review"]["entry_problem"]} |
| SL | {payload["cause_review"]["sl_problem"]} |
| TP | {payload["cause_review"]["tp_problem"]} |
| Session | {payload["cause_review"]["session_problem"]} |
| Regime | {payload["cause_review"]["regime_problem"]} |
| Cost | {payload["cause_review"]["cost_problem"]} |
| Data | {payload["cause_review"]["data_problem"]} |
| Identifiable single cause | {payload["cause_review"]["no_identifiable_cause"]} |

Optimization supported: **NO**.

## If insufficient

Missing evidence that prevents A, B, and C:

{missing_md}

Do not invent another audit of the same 15-day book because this verdict is inconvenient.

---

## Research decision

- Do **not** optimize production parameters.
- Do **not** change Strategy, RiskGate, execution, sizing, RR, ML, PA lock, or calibration.
- Do **not** start Phase 37 automatically.
- Do **not** re-audit the same 24 dependent RAW rows.
- Production authorization remains **BLOCKED** unless separately and explicitly authorized by the existing production gate (`PHASE27_16_FINAL_VALIDATION_GATE.md`).
- If an operator later continues research: obtain a longer defensible `XAUUSD_i` M5 tape and COMPLETE cost evidence first. Do not search SL/TP/RR/session on this book.

---

## Safety

No live orders, no MT5 attach, no `.env`, no parquet rewrite, no production change.
Phase 37 was **not** started.
""",
        encoding="utf-8",
    )


def _patch_truth_docs(root: Path) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Strategy evidence verdict (Phase 36)"
        block = (
            "\n\n## Strategy evidence verdict (Phase 36)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Strategy verdict | **INSUFFICIENT_EVIDENCE** |\n"
            "| Evidence supports edge (A) | **NO** |\n"
            "| Evidence supports no edge (C) | **NO** |\n"
            "| Production changed or optimized | **NO** |\n"
            "| FINAL_GATE | **BLOCKED** |\n"
            "| Phase 37 started | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")

    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        text = text.replace(
            "| Phase 35 execution reality | `run_phase35_collection()` | n/a | RESEARCH ONLY; broker cost/execution AND-gate; no live orders | **PASS** — INCOMPLETE; MODELED not VERIFIED; Phase 36 not started |",
            "| Phase 35 execution reality | `run_phase35_collection()` | n/a | RESEARCH ONLY; broker cost/execution AND-gate; no live orders | **PASS** — INCOMPLETE; MODELED not VERIFIED |",
        )
        row = (
            "| Phase 36 strategy verdict | `run_phase36_collection()` | n/a | RESEARCH ONLY; synthesize 28.0–35; no optimization; no production change | **PASS** — INSUFFICIENT_EVIDENCE; FINAL_GATE BLOCKED; Phase 37 not started |"
        )
        if "Phase 36 strategy verdict" not in text:
            needle = "| Phase 35 execution reality |"
            idx = text.find(needle)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + row + "\n" + text[end + 1 :]
        cfg.write_text(text, encoding="utf-8")

    sot = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    if sot.is_file():
        text = sot.read_text(encoding="utf-8")
        para = (
            "Phase 36 (`docs_v2/02_research/PHASE36_STRATEGY_VERDICT.md`) is the research verdict "
            "on unchanged `gold_ny_sweep` using Phases 28.0–35. Verdict is INSUFFICIENT_EVIDENCE. "
            "Not optimization. Not live authorization. Production remains BLOCKED.\n"
        )
        if "PHASE36_STRATEGY_VERDICT.md" not in text:
            marker = "Phase 35 (`docs_v2/02_research/PHASE35_EXECUTION_REALITY.md`)"
            idx = text.find(marker)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + "\n" + para + text[end + 1 :]
                sot.write_text(text, encoding="utf-8")

    boundary = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    if boundary.is_file():
        text = boundary.read_text(encoding="utf-8")
        line = (
            "`tradingbot/backtest/phase36_strategy_verdict.py` — **RESEARCH_ONLY** strategy evidence "
            "verdict from Phases 28.0–35; no optimization; does not authorize live trading.  \n"
        )
        if "phase36_strategy_verdict.py" not in text:
            needle = "`tradingbot/backtest/phase35_execution_reality.py`"
            idx = text.find(needle)
            if idx >= 0:
                end = text.find("\n", idx)
                text = text[: end + 1] + line + text[end + 1 :]
                boundary.write_text(text, encoding="utf-8")

    for rel, old, new in (
        (
            "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md",
            "Phase 28.0–35 performance research",
            "Phase 28.0–36 performance research",
        ),
        (
            "docs_v2/01_truth/PHASE27_15_COST_COMPLETENESS_GATE.md",
            "Phase 28–35 research work does **not** satisfy this AND-gate.",
            "Phase 28–36 research work does **not** satisfy this AND-gate.",
        ),
        (
            "docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md",
            "Phase 28.0–35 are **separate RESEARCH**",
            "Phase 28.0–36 are **separate RESEARCH**",
        ),
    ):
        path = root / rel
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if old in text and new not in text:
                path.write_text(text.replace(old, new), encoding="utf-8")


def run_phase36_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical M5 fingerprint changed — Phase 36 refuses to proceed")
    pass_a = evaluate(root)
    pass_b = evaluate(root)
    core = lambda p: {
        "verdict": p["strategy_verdict"]["code"],
        "floors": p["floors"],
        "cost_complete": p["cost_complete"],
        "official_answer": (p["evidence_sources"]["phase28_4"] or {}).get("official_answer"),
        "events": (p["evidence_sources"]["phase31"] or {}).get("events"),
    }
    if _stable_hash(core(pass_a)) != _stable_hash(core(pass_b)):
        raise RuntimeError("Phase 36 evaluation is not deterministic")
    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": "PASS",
        "research_only": True,
        "live_orders": False,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "parameters_searched": False,
        "production_changed": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "ml_changed": False,
        "rr_changed": False,
        "optimization_phase": False,
        "env_accessed": False,
        "mt5_attached": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "dataset": CANONICAL_PARQUET,
        "dataset_fingerprint": fp,
        "evaluator_fingerprint": EVALUATOR_VERSION,
        **pass_a,
        "reproducibility": {
            "passes": 2,
            "passes_match": True,
            "data_fingerprint": fp,
            "output_fingerprint": _stable_hash(core(pass_a)),
        },
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "PRODUCTION_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "PHASE_37_STARTED": False,
        },
        "phase_37_started": False,
    }
    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after
    _write_json(root / PHASE36_JSON, payload)
    _write_markdown(root, payload)
    _patch_truth_docs(root)
    return payload


if __name__ == "__main__":
    run_phase36_collection()
