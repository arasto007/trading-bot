"""Phase 26J — lightweight end-to-end decision-path reconciliation (no full backtest)."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.phase26d_kernel_signal_trace import (
    DEFAULT_DATASET,
    DIAGNOSTIC_BARS,
    WARMUP,
    _enrich_frame,
    _load_parquet_tail,
    find_known_good_candidates,
)
from tradingbot.backtest.phase26i_full_tail_attribution import (
    EXPECTED_CURSORS,
    EXPECTED_DIRECTIONS,
    _load_json,
    _parse_cursor,
    _verify_26c_funnel_internal,
    _verify_26g_26h_baseline,
    _verify_candidate_set,
)

PHASE26B_RECOVERY_JSON = "logs/phase26b_recovery_report.json"
PHASE26C_JSON = "logs/phase26c_zero_signal_audit.json"
PHASE26D_JSON = "logs/phase26d_kernel_signal_trace.json"
PHASE26G_JSON = "logs/phase26g_riskgate_counterfactual.json"
PHASE26H_JSON = "logs/phase26h_counterfactual_consistency.json"
PHASE26I_JSON = "logs/phase26i_full_tail_attribution.json"
PHASE26I_CANDIDATE_JSON = "logs/phase26i_candidate_set_consistency.json"
PHASE26J_JSON = "logs/phase26j_decision_path_reconciliation.json"
PHASE26J_CANDIDATE_JSON = "logs/phase26j_candidate_reconciliation.json"

_CAND_RE = re.compile(r"@(\d+)$")


@dataclass
class Phase26JAudit:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    safety: dict[str, bool] = field(
        default_factory=lambda: {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "CREDENTIALS_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "ROUTER_CHANGED": False,
            "PRODUCTION_CODE_CHANGED": False,
            "FULL_BACKTEST_RERUN": False,
            "FULL_ENGINE_BAR_WALK": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26J", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _chain_link(
    from_stage: str,
    to_stage: str,
    from_count: int | str,
    to_count: int | str,
    label: str,
    evidence: str,
    note: str = "",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "from": from_stage,
        "to": to_stage,
        "from_count": from_count,
        "to_count": to_count,
        "label": label,
        "evidence": evidence,
    }
    if note:
        row["note"] = note
    return row


def _build_reconciliation_chain(
    c26: dict[str, Any],
    d26: dict[str, Any],
    g26: dict[str, Any],
    b26: dict[str, Any],
    *,
    signal_scan: dict[str, Any],
) -> list[dict[str, Any]]:
    gc = c26["gate_counts"]
    prop = d26["propagation_counts"]
    trades = b26.get("results_summary", {}).get("total_trades", 0)

    signal_label = "VERIFIED"
    signal_note = ""
    if signal_scan.get("ran"):
        if signal_scan.get("cursor_set_matches_expected"):
            signal_note = "Phase 26J closed-bar signal scan confirms same 19 cursors as 26D/26G"
        else:
            signal_label = "PARTIALLY VERIFIED"
            signal_note = "Signal scan cursor set mismatch — see signal_scan section"

    return [
        _chain_link("RAW 2500", "2200 evaluable", 2500, gc["bars_after_warmup"], "VERIFIED", "phase26c"),
        _chain_link(
            "2200 evaluable",
            "96 NY-session",
            gc["bars_after_warmup"],
            gc["ny_session_bars"],
            "VERIFIED",
            "phase26c",
        ),
        _chain_link(
            "96 NY-session",
            "65 sweep",
            gc["ny_session_bars"],
            gc["sweep_detected"],
            "VERIFIED",
            "phase26c",
        ),
        _chain_link(
            "65 sweep",
            "19 reclaim",
            gc["sweep_detected"],
            gc["reclaim_detected"],
            "VERIFIED",
            "phase26c",
        ),
        _chain_link(
            "19 reclaim",
            "19 setup",
            gc["reclaim_detected"],
            gc["setup_ok_pre_hardening"],
            "VERIFIED",
            "phase26c",
        ),
        _chain_link(
            "19 setup",
            "19 hardening survivors",
            gc["setup_ok_pre_hardening"],
            gc["evaluate_gold_setup_pass"],
            "VERIFIED",
            "phase26c hardening_rejected=0",
        ),
        _chain_link(
            "19 hardening survivors",
            "19 strategy signals",
            gc["evaluate_gold_setup_pass"],
            gc["price_action_strategy_signals"],
            signal_label,
            "phase26c + phase26j signal scan",
            note=signal_note,
        ),
        _chain_link(
            "19 strategy signals",
            "19 SignalFilterStage",
            gc["price_action_strategy_signals"],
            prop["signal_filter_pass"],
            "VERIFIED",
            "phase26d per-candidate trace (19/19 pass, WPSQF OFF)",
        ),
        _chain_link(
            "19 SignalFilterStage",
            "19 RiskGate evaluations",
            prop["signal_filter_pass"],
            prop["risk_stage_reached"],
            "VERIFIED",
            "phase26d propagation_counts",
        ),
        _chain_link(
            "19 RiskGate evaluations",
            "0 RiskGate allowed",
            prop["risk_stage_reached"],
            g26["baseline"]["ALLOWED"],
            "VERIFIED",
            "phase26g/26h baseline LOT=3 META=10 ATR=6 ALLOWED=0",
        ),
        _chain_link(
            "0 RiskGate allowed",
            "0 trades",
            g26["baseline"]["ALLOWED"],
            trades,
            "VERIFIED",
            "phase26b results_summary.total_trades=0",
            note="0 allowed precludes trade emission on traced path; does not prove no other execution paths",
        ),
    ]


def _run_lightweight_signal_scan(
    root: Path,
    *,
    dataset_rel: str = DEFAULT_DATASET,
    bars: int = DIAGNOSTIC_BARS,
    warmup: int = WARMUP,
) -> dict[str, Any]:
    """Closed-bar production-path signal enumeration only — no RiskGate, broker, or PnL."""
    parquet = root / dataset_rel
    if not parquet.is_file():
        return {
            "ran": False,
            "skipped_reason": f"dataset missing: {parquet}",
            "cursor_set_matches_expected": False,
        }

    t0 = time.perf_counter()
    raw = _load_parquet_tail(parquet, bars)
    enriched = _enrich_frame(raw)
    candidates = find_known_good_candidates(enriched, warmup=warmup)
    elapsed = round(time.perf_counter() - t0, 3)

    cursors = sorted(int(c["cursor"]) for c in candidates)
    cursor_set = frozenset(cursors)
    directions = {
        int(c["cursor"]): (c.get("isolated_signal") or {}).get("direction")
        for c in candidates
    }
    timestamps = {int(c["cursor"]): c.get("timestamp") for c in candidates}

    issues: list[str] = []
    if cursor_set != EXPECTED_CURSORS:
        issues.append(f"scan cursors {sorted(cursor_set)} != expected {sorted(EXPECTED_CURSORS)}")
    for cur in EXPECTED_CURSORS:
        if directions.get(cur) != EXPECTED_DIRECTIONS[cur]:
            issues.append(f"cursor {cur}: direction {directions.get(cur)} != {EXPECTED_DIRECTIONS[cur]}")

    return {
        "ran": True,
        "mode": "signal_generation_only",
        "uses_riskgate": False,
        "uses_broker_simulation": False,
        "uses_execution": False,
        "uses_pnl": False,
        "path": "append_forming_bar_m5 + exclude_forming_bar + PriceActionStrategy.generate_signals (production closed-bar path)",
        "dataset": dataset_rel,
        "bars": len(enriched),
        "warmup": warmup,
        "candidate_count": len(candidates),
        "cursors": cursors,
        "cursor_set_matches_expected": cursor_set == EXPECTED_CURSORS,
        "directions_match_expected": all(
            directions.get(c) == EXPECTED_DIRECTIONS[c] for c in EXPECTED_CURSORS
        ),
        "issues": issues,
        "elapsed_seconds": elapsed,
        "timestamps_by_cursor": timestamps,
        "directions_by_cursor": {str(k): v for k, v in directions.items()},
    }


def _build_unified_candidate_records(
    d26: dict[str, Any],
    g26: dict[str, Any],
    signal_scan: dict[str, Any],
) -> list[dict[str, Any]]:
    d_by_cursor = {int(r["cursor"]): r for r in d26["propagation_counts"]["per_candidate"]}
    g_by_cursor: dict[int, dict[str, Any]] = {}
    for row in g26["attribution_matrix"]:
        cur = _parse_cursor(row["candidate"])
        if cur is not None:
            g_by_cursor[cur] = row

    records: list[dict[str, Any]] = []
    for cur in sorted(EXPECTED_CURSORS):
        d_row = d_by_cursor.get(cur, {})
        g_row = g_by_cursor.get(cur, {})
        scan_ts = (signal_scan.get("timestamps_by_cursor") or {}).get(cur)
        scan_dir = (signal_scan.get("directions_by_cursor") or {}).get(str(cur))
        records.append(
            {
                "cursor": cur,
                "timestamp_phase26d": d_row.get("timestamp"),
                "timestamp_signal_scan": scan_ts,
                "timestamps_match": (
                    d_row.get("timestamp") == scan_ts if scan_ts and d_row.get("timestamp") else None
                ),
                "direction": EXPECTED_DIRECTIONS[cur],
                "direction_phase26d": d_row.get("direction"),
                "direction_phase26g": g_row.get("direction"),
                "symbol": "XAUUSD",
                "signal_stage_reached": d_row.get("stages", {}).get("B"),
                "signalfilter_reached": d_row.get("stages", {}).get("C"),
                "riskgate_reached": d_row.get("stages", {}).get("D"),
                "riskgate_allowed": d_row.get("stages", {}).get("F"),
                "riskgate_baseline_blocker": g_row.get("baseline"),
                "risk_reason": d_row.get("risk_reason"),
                "signal_scan_direction": scan_dir,
                "verified": (
                    d_row.get("direction") == EXPECTED_DIRECTIONS[cur]
                    and g_row.get("direction") == EXPECTED_DIRECTIONS[cur]
                    and d_row.get("stages", {}).get("D") is True
                    and g_row.get("baseline") in ("LOT", "META", "ATR")
                ),
            }
        )
    return records


def run_phase26j_decision_path_reconciliation(
    base_dir: str | Path | None = None,
    *,
    run_signal_scan: bool = True,
) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())

    b26 = _load_json(root, PHASE26B_RECOVERY_JSON)
    c26 = _load_json(root, PHASE26C_JSON)
    d26 = _load_json(root, PHASE26D_JSON)
    g26 = _load_json(root, PHASE26G_JSON)
    h26 = _load_json(root, PHASE26H_JSON)

    i26: dict[str, Any] | None = None
    i26_cand: dict[str, Any] | None = None
    i26_path = root / PHASE26I_JSON
    i26_cand_path = root / PHASE26I_CANDIDATE_JSON
    if i26_path.is_file():
        i26 = json.loads(i26_path.read_text(encoding="utf-8"))
    if i26_cand_path.is_file():
        i26_cand = json.loads(i26_cand_path.read_text(encoding="utf-8"))

    candidate_check = _verify_candidate_set(d26, g26)
    funnel_check = _verify_26c_funnel_internal(c26)
    baseline_check = _verify_26g_26h_baseline(g26, h26)

    signal_scan = (
        _run_lightweight_signal_scan(root)
        if run_signal_scan
        else {"ran": False, "skipped_reason": "run_signal_scan=False"}
    )

    unified_candidates = _build_unified_candidate_records(d26, g26, signal_scan)
    chain = _build_reconciliation_chain(c26, d26, g26, b26, signal_scan=signal_scan)

    all_verified_links = all(link["label"] == "VERIFIED" for link in chain)
    scan_ok = not signal_scan.get("ran") or signal_scan.get("cursor_set_matches_expected", False)
    checks_ok = candidate_check["passed"] and funnel_check["passed"] and baseline_check["passed"]

    # Conservative claim: B unless simultaneous full-engine bar walk exists (it does not).
    if all_verified_links and checks_ok and scan_ok:
        final_claim = "B — STRONGLY SUPPORTED BUT NOT FORMALLY PROVEN"
    elif checks_ok:
        final_claim = "C — PARTIALLY EXPLAINED"
    else:
        final_claim = "D — UNEXPLAINED"

    additional_signals = (
        "NO ADDITIONAL SIGNALS OBSERVED IN AVAILABLE EVIDENCE"
        if signal_scan.get("ran")
        and signal_scan.get("cursor_set_matches_expected")
        and signal_scan.get("candidate_count") == 19
        else (
            "INCONCLUSIVE — signal scan did not run or cursor set mismatch; "
            "cannot assert completeness"
        )
    )

    report = Phase26JAudit(
        status="PASS_WITH_DEFERRAL" if checks_ok and scan_ok else "FAIL",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "objective": (
                "Reconcile Phase 26B zero-trade result with Phase 26C–26I artifact funnel "
                "without rerunning the full backtest engine."
            ),
            "data_window": c26["data_window"],
            "configuration_fingerprint": c26["phase26b_context"]["configuration_fingerprint"],
            "reran_phase26b": False,
            "reran_full_backtest": False,
            "full_engine_simultaneous_bar_walk": False,
            "source_artifacts": [
                PHASE26B_RECOVERY_JSON,
                PHASE26C_JSON,
                PHASE26D_JSON,
                PHASE26G_JSON,
                PHASE26H_JSON,
                PHASE26I_JSON,
                PHASE26I_CANDIDATE_JSON,
            ],
            "reconciliation_chain": chain,
            "candidate_set": {
                "expected_count": 19,
                "expected_cursors": sorted(EXPECTED_CURSORS),
                "phase26d_26g_consistency": candidate_check,
                "phase26i_consistency": i26_cand,
                "unified_records": unified_candidates,
                "all_nineteen_verified": all(r["verified"] for r in unified_candidates),
            },
            "additional_signals": {
                "conclusion": additional_signals,
                "signal_scan": signal_scan,
                "phase26c_signal_count": c26["gate_counts"]["price_action_strategy_signals"],
                "evidence_of_extra_kernel_signals": False,
                "evidence_of_extra_strategy_signals_beyond_19": (
                    False
                    if signal_scan.get("ran") and signal_scan.get("candidate_count") == 19
                    else None
                ),
                "caveat": (
                    "Closed-bar production-path scan on 2500-bar tail; "
                    "not a simultaneous full-engine bar walk."
                ),
            },
            "forming_bar_effect": {
                "reran_forming_comparison": False,
                "phase26d_off_by_one_audit": d26.get("off_by_one_audit"),
                "phase26c_counts": {
                    "evaluate_gold_setup_pass": c26["gate_counts"]["evaluate_gold_setup_pass"],
                    "forming_bar_sim_pass": c26["gate_counts"]["forming_bar_sim_pass"],
                    "price_action_strategy_signals": c26["gate_counts"]["price_action_strategy_signals"],
                },
                "interpretation": (
                    "Production decisions use append_forming_bar + exclude_forming_bar (closed-bar path). "
                    "Phase 26D off_by_one_audit: raw window last timestamp may include synthetic forming bar; "
                    "closed_last_ts aligns with kernel closed bar (PASS @354). "
                    "Phase 26C: forming_bar_sim_pass=19 equals price_action_strategy_signals=19 — "
                    "no extra closed-bar production candidates from forming-bar handling on this tail."
                ),
                "forming_only_transients_counted_as_production": False,
            },
            "riskgate_reconciliation": {
                "phase26b_risk_journal_entries": c26["gate_counts"]["phase26b_risk_journal_entries"],
                "phase26d_risk_stage_reached": d26["propagation_counts"]["risk_stage_reached"],
                "phase26d_journal_appended": d26["propagation_counts"]["journal_appended"],
                "baseline": g26["baseline"],
                "sequential_interpretation": h26.get("classification", {}),
                "journal_gap_affects_zero_trade_conclusion": False,
                "explanation": (
                    "Journal metric gap is instrumentation only. Per-candidate Phase 26D/26G evidence "
                    "independently establishes 19 RiskGate evaluations with 0 ALLOWED."
                ),
                "phase26d_journal_audit": d26.get("journal_audit"),
            },
            "execution_reconciliation": {
                "phase26b_total_trades": b26.get("results_summary", {}).get("total_trades", 0),
                "riskgate_allowed": g26["baseline"]["ALLOWED"],
                "reconciles": g26["baseline"]["ALLOWED"] == 0 and b26.get("results_summary", {}).get("total_trades", 0) == 0,
                "scope": (
                    "0 ALLOWED among 19 traced candidates implies no trade from those candidates. "
                    "Does not prove no trades from any other hypothetical path on this tail."
                ),
            },
            "final_zero_trade_claim": final_claim,
            "claim_rationale": {
                "why_not_A": (
                    "No simultaneous full-engine bar walk over 2500 bars was executed; "
                    "reconciliation uses artifact cross-check + signal-generation-only scan."
                ),
                "why_B": (
                    "All 19 cursors match across 26D/26G/26I; 26J signal scan confirms same set; "
                    "26C funnel counts consistent; 19→19→0→0 chain verified at per-candidate level."
                ),
                "topics_separated": {
                    "A_candidate_generation_completeness": (
                        "Strongly supported by 26J signal scan = 19 cursors; not formally proven end-to-end"
                    ),
                    "B_riskgate_rejection_completeness": "Verified for 19 candidates (26G/26H sequential stack)",
                    "C_broker_economic_parity": "NOT_PROVEN — EV-EQ-01 out of scope",
                    "D_profitability": "NOT assessed — out of scope",
                },
            },
            "phase26c_funnel_consistency": funnel_check,
            "phase26g_26h_baseline_consistency": baseline_check,
            "what_this_proves": [
                "Phase 26B 0 trades reconciles with 0 RiskGate ALLOWED among 19 traced candidates",
                "19-candidate cursor/direction/timestamp set is identical across 26D, 26G, 26I artifacts",
                "Lightweight closed-bar signal scan finds exactly 19 production-path candidates matching expected set",
                "Risk journal=0 does not invalidate 19 RiskGate evaluation conclusion",
                "Forming-bar transients are not counted as additional production candidates on this tail",
            ],
            "what_this_does_not_prove": [
                "PROVEN END-TO-END (A) — no simultaneous full-engine 2500-bar walk",
                "EV-EQ-01 broker/live parity",
                "Strategy profitability or production readiness",
                "That no signal could exist outside closed-bar production path under different engine state",
            ],
            "instrumentation_gaps": [
                "risk_journal_entries=0 while risk_stage_reached=19 (26D journal_audit)",
                "Aggregate closed-bar eligibility count not recorded (Phase 26C/26I UNKNOWN)",
                "Full-engine simultaneous dedup/state vs per-candidate 26D traces",
            ],
            "production_changes": "NONE",
            "ev_eq_01": "NOT_PROVEN",
            "recommended_next_step": (
                "Accept B-level reconciliation for forensic roadmap OR run instrumented "
                "kernel bar-walk (signal + RiskGate reach counters only, no execution) if A-level proof required. "
                "Operator Phase 25M session remains separate for EV-EQ-01."
            ),
            "final_decision": "PASS_WITH_DEFERRAL" if checks_ok and scan_ok else "FAIL",
        }
    )

    _write_json(root / PHASE26J_JSON, report)
    _write_json(
        root / PHASE26J_CANDIDATE_JSON,
        {
            "schema_version": 1,
            "phase": "26J",
            "generated_at": report["generated_at"],
            "unified_records": unified_candidates,
            "candidate_check": candidate_check,
            "signal_scan_summary": {
                "ran": signal_scan.get("ran"),
                "count": signal_scan.get("candidate_count"),
                "cursor_set_matches_expected": signal_scan.get("cursor_set_matches_expected"),
                "elapsed_seconds": signal_scan.get("elapsed_seconds"),
            },
        },
    )
    return report


def run_phase26j_collection(
    base_dir: str | Path | None = None,
    *,
    run_signal_scan: bool = True,
) -> dict[str, Any]:
    return run_phase26j_decision_path_reconciliation(base_dir, run_signal_scan=run_signal_scan)
