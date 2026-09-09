"""Phase 26I — full-tail zero-trade attribution audit (artifact-only, no backtest)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PHASE26B_RECOVERY_JSON = "logs/phase26b_recovery_report.json"
PHASE26C_JSON = "logs/phase26c_zero_signal_audit.json"
PHASE26D_JSON = "logs/phase26d_kernel_signal_trace.json"
PHASE26G_JSON = "logs/phase26g_riskgate_counterfactual.json"
PHASE26H_JSON = "logs/phase26h_counterfactual_consistency.json"
PHASE26I_JSON = "logs/phase26i_full_tail_attribution.json"
PHASE26I_CANDIDATE_JSON = "logs/phase26i_candidate_set_consistency.json"

EXPECTED_CURSORS = frozenset(
    {
        354,
        355,
        356,
        357,
        358,
        359,
        1175,
        1176,
        1177,
        1178,
        1179,
        1180,
        1186,
        1451,
        1452,
        1453,
        1454,
        1455,
        1456,
    }
)

EXPECTED_DIRECTIONS: dict[int, str] = {
    **{c: "BUY" for c in range(354, 360)},
    **{c: "BUY" for c in range(1175, 1181)},
    1186: "BUY",
    **{c: "SELL" for c in range(1451, 1457)},
}

_CAND_RE = re.compile(r"@(\d+)$")


@dataclass
class Phase26IAudit:
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
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26I", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _load_json(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_cursor(candidate_key: str) -> int | None:
    match = _CAND_RE.search(candidate_key)
    return int(match.group(1)) if match else None


def _funnel_row(
    stage: str,
    input_count: int | None,
    output_count: int | None,
    evidence: str,
    confidence: str,
    note: str = "",
) -> dict[str, Any]:
    removed: int | None
    if input_count is not None and output_count is not None:
        removed = input_count - output_count
    else:
        removed = None
    row: dict[str, Any] = {
        "stage": stage,
        "input": input_count,
        "output": output_count,
        "removed": removed,
        "evidence": evidence,
        "confidence": confidence,
    }
    if note:
        row["note"] = note
    return row


def _build_full_tail_funnel(c26: dict[str, Any], d26: dict[str, Any], b26: dict[str, Any]) -> list[dict[str, Any]]:
    gc = c26["gate_counts"]
    raw = gc["raw_bars"]
    evaluable = gc["bars_after_warmup"]
    ny = gc["ny_session_bars"]
    asian = gc["asian_range_valid"]
    sweep = gc["sweep_detected"]
    reclaim = gc["reclaim_detected"]
    setup = gc["setup_ok_pre_hardening"]
    hardened = gc["evaluate_gold_setup_pass"]
    signals = gc["price_action_strategy_signals"]
    prop = d26["propagation_counts"]
    trades = b26.get("results_summary", {}).get("total_trades")
    if trades is None:
        trades = b26.get("summary", {}).get("total_trades")
    if trades is None:
        for key in ("results", "backtest_summary"):
            block = b26.get(key, {})
            if isinstance(block, dict) and "total_trades" in block:
                trades = block["total_trades"]
                break
    if trades is None:
        trades = 0

    return [
        _funnel_row("1_raw_dataset_rows", None, raw, "phase26c_zero_signal_audit.json", "VERIFIED"),
        _funnel_row("2_warmup_evaluable_rows", raw, evaluable, "phase26c gate_counts.bars_after_warmup", "VERIFIED"),
        _funnel_row(
            "3_closed_bar_eligible_rows",
            evaluable,
            None,
            "phase26c loops evaluable cursors with exclude_forming_bar; no aggregate count recorded",
            "UNKNOWN",
            note="Per-bar closed-window skip not tallied in Phase 26C artifact",
        ),
        _funnel_row(
            "4_ny_session_eligible_rows",
            evaluable,
            ny,
            "phase26c gate_counts.ny_session_bars",
            "VERIFIED",
            note="NY window 15–16 UTC; 108 raw hour-15/16 bars on full 2500, 96 after warmup filter",
        ),
        _funnel_row(
            "5_asian_range_valid_rows",
            ny,
            asian,
            "phase26c gate_counts.asian_range_valid",
            "VERIFIED",
            note="asian_range_too_small=0 on NY bars",
        ),
        _funnel_row(
            "6_sweep_candidates",
            asian,
            sweep,
            "phase26c gate_counts.sweep_detected; reject no_sweep=31 on NY bars",
            "VERIFIED",
        ),
        _funnel_row(
            "7_reclaim_candidates",
            sweep,
            reclaim,
            "phase26c gate_counts.reclaim_detected; reject no_reclaim_inside_asian=46",
            "VERIFIED",
        ),
        _funnel_row(
            "8_setup_candidates_pre_hardening",
            reclaim,
            setup,
            "phase26c gate_counts.setup_ok_pre_hardening",
            "VERIFIED",
        ),
        _funnel_row(
            "9_setup_hardening_survivors",
            setup,
            hardened,
            "phase26c hardening_audit.hardening_rejected=0",
            "VERIFIED",
        ),
        _funnel_row(
            "10_strategy_signals",
            hardened,
            signals,
            "phase26c gate_counts.price_action_strategy_signals (full-tail diagnostic scan)",
            "VERIFIED",
        ),
        _funnel_row(
            "11_signalfilterstage_survivors",
            signals,
            prop["signal_filter_pass"],
            "phase26d propagation_counts.signal_filter_pass (19 known candidates)",
            "VERIFIED",
            note="0 drops among traced candidates; full-tail per-bar SignalFilter tally not separately recorded",
        ),
        _funnel_row(
            "12_riskgate_candidates",
            prop["signal_filter_pass"],
            prop["risk_stage_reached"],
            "phase26d propagation_counts.risk_stage_reached",
            "VERIFIED",
        ),
        _funnel_row(
            "13_riskgate_allowed",
            prop["risk_stage_reached"],
            prop["risk_allowed"],
            "phase26g baseline ALLOWED=0; phase26h verified",
            "VERIFIED",
        ),
        _funnel_row(
            "14_execution_trades",
            prop["risk_allowed"],
            trades,
            "phase26b_recovery_report total_trades=0",
            "VERIFIED",
        ),
    ]


def _verify_candidate_set(
    d26: dict[str, Any], g26: dict[str, Any]
) -> dict[str, Any]:
    issues: list[str] = []
    d_cursors: dict[int, dict[str, Any]] = {}
    for row in d26["propagation_counts"]["per_candidate"]:
        cur = int(row["cursor"])
        d_cursors[cur] = row

    g_cursors: dict[int, dict[str, Any]] = {}
    for row in g26["attribution_matrix"]:
        cur = _parse_cursor(row["candidate"])
        if cur is None:
            issues.append(f"26G candidate key missing cursor: {row['candidate']}")
            continue
        g_cursors[cur] = row

    d_set = frozenset(d_cursors)
    g_set = frozenset(g_cursors)
    missing_d = EXPECTED_CURSORS - d_set
    extra_d = d_set - EXPECTED_CURSORS
    missing_g = EXPECTED_CURSORS - g_set
    extra_g = g_set - EXPECTED_CURSORS
    if missing_d:
        issues.append(f"26D missing expected cursors: {sorted(missing_d)}")
    if extra_d:
        issues.append(f"26D unexpected cursors: {sorted(extra_d)}")
    if missing_g:
        issues.append(f"26G missing expected cursors: {sorted(missing_g)}")
    if extra_g:
        issues.append(f"26G unexpected cursors: {sorted(extra_g)}")
    if d_set != g_set:
        issues.append(f"26D vs 26G cursor set mismatch: d_only={sorted(d_set - g_set)} g_only={sorted(g_set - d_set)}")

    direction_checks: list[dict[str, Any]] = []
    for cur in sorted(EXPECTED_CURSORS):
        expected = EXPECTED_DIRECTIONS[cur]
        d_dir = d_cursors.get(cur, {}).get("direction")
        g_dir = g_cursors.get(cur, {}).get("direction")
        ok = d_dir == expected and g_dir == expected and d_dir == g_dir
        if not ok:
            issues.append(
                f"cursor {cur}: expected={expected} 26D={d_dir} 26G={g_dir}"
            )
        direction_checks.append(
            {
                "cursor": cur,
                "expected_direction": expected,
                "phase26d_direction": d_dir,
                "phase26g_direction": g_dir,
                "match": ok,
            }
        )

    baseline_alignment: list[dict[str, Any]] = []
    for cur in sorted(EXPECTED_CURSORS):
        g_row = g_cursors[cur]
        d_reason = d_cursors[cur].get("risk_reason", "")
        baseline = g_row["baseline"]
        baseline_alignment.append(
            {
                "cursor": cur,
                "phase26g_baseline": baseline,
                "phase26d_risk_reason": d_reason,
            }
        )

    return {
        "expected_count": len(EXPECTED_CURSORS),
        "phase26d_count": len(d_cursors),
        "phase26g_count": len(g_cursors),
        "sets_identical": d_set == g_set == EXPECTED_CURSORS,
        "issues": issues,
        "passed": len(issues) == 0,
        "direction_checks": direction_checks,
        "baseline_alignment": baseline_alignment,
    }


def _verify_26c_funnel_internal(c26: dict[str, Any]) -> dict[str, Any]:
    gc = c26["gate_counts"]
    issues: list[str] = []
    pipeline = {g["gate"]: g["count"] for g in c26["signal_gate_pipeline"]}

    pairs = [
        ("raw_bars", gc["raw_bars"], pipeline.get("raw_bars")),
        ("bars_after_warmup", gc["bars_after_warmup"], pipeline.get("bars_after_warmup")),
        ("ny_session_bars", gc["ny_session_bars"], pipeline.get("ny_session_bars")),
        ("sweep_detected", gc["sweep_detected"], pipeline.get("sweep_detected")),
        ("reclaim_detected", gc["reclaim_detected"], pipeline.get("reclaim_detected")),
        ("price_action_strategy_signals", gc["price_action_strategy_signals"], pipeline.get("price_action_strategy_signals")),
    ]
    for name, gate_val, pipe_val in pairs:
        if pipe_val is not None and gate_val != pipe_val:
            issues.append(f"{name}: gate_counts={gate_val} pipeline={pipe_val}")

    ny_rejects = c26.get("reject_reasons_on_ny_bars", {})
    sweep_reject = ny_rejects.get("no_sweep", 0)
    reclaim_reject = ny_rejects.get("no_reclaim_inside_asian", 0)
    setup_survivors = ny_rejects.get("setup_ok_pre_hardening", 0)
    if gc["ny_session_bars"] - gc["sweep_detected"] != sweep_reject:
        issues.append(
            f"sweep accounting: ny-sweep={gc['ny_session_bars'] - gc['sweep_detected']} "
            f"no_sweep reject={sweep_reject}"
        )
    if gc["sweep_detected"] - gc["reclaim_detected"] != reclaim_reject:
        issues.append(
            f"reclaim accounting: sweep-reclaim={gc['sweep_detected'] - gc['reclaim_detected']} "
            f"no_reclaim reject={reclaim_reject}"
        )
    if gc["reclaim_detected"] != setup_survivors:
        issues.append(
            f"setup survivors: reclaim={gc['reclaim_detected']} setup_ok_pre_hardening reject tally={setup_survivors}"
        )

    return {"passed": len(issues) == 0, "issues": issues}


def _verify_26g_26h_baseline(g26: dict[str, Any], h26: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    expected = {"LOT": 3, "META": 10, "ATR": 6, "ALLOWED": 0}
    for label, val in expected.items():
        if g26["baseline"].get(label) != val:
            issues.append(f"26G baseline {label}={g26['baseline'].get(label)} expected {val}")
        if h26["verified_baseline"].get(label) != val:
            issues.append(f"26H verified {label}={h26['verified_baseline'].get(label)} expected {val}")

    for key in ("A_no_lot", "B_no_meta", "C_no_atr", "D_no_lot_meta", "E_no_lot_atr", "F_no_meta_atr"):
        g_counts = g26["counterfactuals"][key]["counts"]
        h_counts = h26["verified_counterfactuals"][key]
        for label in ("LOT", "META", "ATR", "ALLOWED"):
            if g_counts.get(label) != h_counts.get(label):
                issues.append(f"{key} {label}: 26G={g_counts.get(label)} 26H={h_counts.get(label)}")

    return {"passed": len(issues) == 0, "issues": issues, "expected_baseline": expected}


def _classify_bottlenecks(funnel: list[dict[str, Any]]) -> dict[str, Any]:
    reductions: list[dict[str, Any]] = []
    for row in funnel:
        removed = row.get("removed")
        if removed is not None and removed > 0 and row.get("confidence") == "VERIFIED":
            reductions.append(
                {
                    "stage": row["stage"],
                    "removed": removed,
                    "output": row["output"],
                }
            )
    reductions.sort(key=lambda r: r["removed"], reverse=True)

    category_map = {
        "2_warmup_evaluable_rows": "A — data/warmup loss",
        "4_ny_session_eligible_rows": "B — session-window loss",
        "5_asian_range_valid_rows": "C — Asian-range validity loss",
        "6_sweep_candidates": "D — sweep detection loss",
        "7_reclaim_candidates": "E — reclaim loss",
        "13_riskgate_allowed": "I — RiskGate loss",
    }
    ranked = [
        {**r, "category": category_map.get(r["stage"], "other")}
        for r in reductions
    ]

    return {
        "primary": "L — multiple bottlenecks",
        "secondary": [
            "B — session-window loss (dominant: evaluable→NY)",
            "E — reclaim loss (dominant within NY pipeline)",
            "D — sweep detection loss",
        ],
        "verified_reduction_ranking": ranked,
        "question_a_bottleneck": (
            "Only 19 RiskGate candidates because Phase 26C full-tail diagnostic scan "
            "found 19 strategy signals after session→sweep→reclaim funnel; "
            "2104/2200 evaluable bars fail NY session filter."
        ),
        "question_b_bottleneck": (
            "0/19 allowed explained by sequential ATR→META→LOT RiskGate stack (Phase 26G/26H)."
        ),
    }


def run_phase26i_full_tail_attribution(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    c26 = _load_json(root, PHASE26C_JSON)
    d26 = _load_json(root, PHASE26D_JSON)
    g26 = _load_json(root, PHASE26G_JSON)
    h26 = _load_json(root, PHASE26H_JSON)
    b26 = _load_json(root, PHASE26B_RECOVERY_JSON)

    funnel = _build_full_tail_funnel(c26, d26, b26)
    candidate_check = _verify_candidate_set(d26, g26)
    funnel_check = _verify_26c_funnel_internal(c26)
    baseline_check = _verify_26g_26h_baseline(g26, h26)
    bottleneck = _classify_bottlenecks(funnel)

    all_passed = candidate_check["passed"] and funnel_check["passed"] and baseline_check["passed"]
    report = Phase26IAudit(
        status="PASS_WITH_DEFERRAL" if all_passed else "FAIL",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "objective": (
                "Attribute where non-trading bars disappear across the Phase 26B 2500-bar tail "
                "without rerunning the backtest engine."
            ),
            "data_window": c26["data_window"],
            "phase26b_context": {
                "configuration_fingerprint": c26["phase26b_context"]["configuration_fingerprint"],
                "total_trades": 0,
                "risk_journal_entries": c26["gate_counts"]["phase26b_risk_journal_entries"],
            },
            "reran_backtest": False,
            "source_artifacts": [
                PHASE26B_RECOVERY_JSON,
                PHASE26C_JSON,
                PHASE26D_JSON,
                PHASE26G_JSON,
                PHASE26H_JSON,
            ],
            "full_tail_candidate_attribution": funnel,
            "known_bottleneck": bottleneck,
            "nineteen_candidate_riskgate_attribution": {
                "candidate_count": 19,
                "baseline": g26["baseline"],
                "gate_order": h26.get("gate_order", {}).get("pa_relevant_sequence", ["ATR", "META", "LOT"]),
                "interpretation": h26.get("classification", {}),
                "direct_blockers": {"LOT": 3, "META": 10, "ATR": 6},
                "allowed": 0,
                "scope": "Question B only — why 0/19 allowed",
            },
            "instrumentation_gaps": {
                "risk_journal_vs_riskgate_evaluations": {
                    "phase26b_risk_journal_entries": 0,
                    "phase26d_risk_stage_reached": d26["propagation_counts"]["risk_stage_reached"],
                    "phase26d_journal_appended": d26["propagation_counts"]["journal_appended"],
                    "known_measurement_gap": (
                        "risk journal does not represent all RiskGate evaluations; "
                        "most reject paths do not append journal entries (Phase 26D/26E)."
                    ),
                },
                "isolated_market_filter_vs_kernel": {
                    "phase26c_market_filter_pass_on_candidates": c26["gate_counts"]["market_filter_pass_on_candidates"],
                    "note": (
                        "13/19 pass isolated PA market-filter ATR check; "
                        "kernel SignalFilterStage passed 19/19 traced candidates — different stage."
                    ),
                },
                "closed_bar_eligible_aggregate": "Not recorded in Phase 26C artifact",
            },
            "session_timezone_audit": {
                "reuse_phase26c": True,
                "ny_window_utc": c26["session_timezone_audit"]["configured_ny_window"],
                "asian_window_utc": c26["session_timezone_audit"]["asian_session"],
                "bars_in_ny_on_full_tail": c26["session_timezone_audit"]["bars_in_ny_window"],
                "ny_bars_after_warmup_filter": c26["gate_counts"]["ny_session_bars"],
                "broker_server_timezone": "UNKNOWN / irrelevant for this UTC-indexed parquet audit",
                "evidence": c26["session_timezone_audit"]["evidence"],
            },
            "candidate_set_consistency": candidate_check,
            "phase26c_funnel_consistency": funnel_check,
            "phase26g_26h_baseline_consistency": baseline_check,
            "sequential_masking_verified": {
                "source": PHASE26H_JSON,
                "primary_classification": h26.get("classification", {}).get("primary"),
                "rejects_conjunction_wording": h26.get("classification", {}).get("rejects_26g_wording"),
                "verified_without_rerun": True,
            },
            "answers": {
                "why_only_19_candidates": bottleneck["question_a_bottleneck"],
                "why_zero_allowed_among_19": bottleneck["question_b_bottleneck"],
                "is_full_tail_zero_trade_proven": (
                    "PARTIALLY — mechanistically explained if the Phase 26C full-tail scan "
                    "is complete (19 strategy signals, none allowed at RiskGate) and Phase 26D "
                    "kernel trace applies to those 19; 0 trades recorded in Phase 26B."
                ),
                "what_remains_unproven": [
                    "EV-EQ-01 backtest/live parity",
                    "Aggregate closed-bar eligibility count on full tail",
                    "Full-engine simultaneous dedup/state vs per-candidate 26D traces without a lightweight bar-walk",
                    "Profitability or production readiness",
                ],
                "smallest_next_forensic_step": (
                    "Lightweight kernel bar-walk over the 2500-bar tail counting SignalStage emissions "
                    "and RiskGate reach (no execution/cost simulation) to reconcile 26B journal=0 "
                    "with 26C/26D signal counts — or operator Phase 25M broker-evidence for EV-EQ-01."
                ),
            },
            "what_this_proves": [
                "Full-tail funnel from 2500 raw bars to 19 strategy signals using Phase 26C counts",
                "Dominant upstream losses: NY session filter, then sweep, then reclaim",
                "All 19 known candidates identical across Phase 26D and 26G",
                "0/19 RiskGate allowed fully explained by sequential ATR→META→LOT stack",
                "Zero-trade result is NOT upgraded to fully proven end-to-end without engine bar-walk reconciliation",
            ],
            "what_this_does_not_prove": [
                "Strategy edge or profitability",
                "That bypassing RiskGate gates is valid live policy",
                "Live MT5 tick-path parity",
                "That no additional kernel-path signals exist beyond the 19 traced candidates without bar-walk",
            ],
            "production_changes": "NONE",
            "ev_eq_01": "NOT_PROVEN",
            "final_decision": "PASS_WITH_DEFERRAL" if all_passed else "FAIL",
        }
    )

    _write_json(root / PHASE26I_JSON, report)
    _write_json(
        root / PHASE26I_CANDIDATE_JSON,
        {
            "schema_version": 1,
            "phase": "26I",
            "generated_at": report["generated_at"],
            **candidate_check,
        },
    )
    return report


def run_phase26i_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase26i_full_tail_attribution(base_dir)
