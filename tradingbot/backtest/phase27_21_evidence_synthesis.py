"""Phase 27.21 — evidence synthesis and remaining-blocker audit.

Read-only. Does not collect MT5 data, weaken gates, or change production behavior.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.cost_model import (
    CostAvailability,
    availability_blocks_completeness,
)
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON

PHASE2721_JSON = "logs/phase27_21_evidence_synthesis.json"
PHASE2721_MD = "docs_v2/01_truth/PHASE27_21_EVIDENCE_SYNTHESIS.md"

PROVEN = "PROVEN"
PARTIAL = "PARTIAL"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
NOT_APPLICABLE = "NOT_APPLICABLE"
ALLOWED_STATUSES = frozenset({PROVEN, PARTIAL, UNKNOWN, BLOCKED, NOT_APPLICABLE})

ARTIFACTS = {
    "phase27_8": "logs/phase27_8_policy_lock.json",
    "phase27_15": "logs/phase27_15_cost_completeness_gate.json",
    "phase27_16": PHASE2716_JSON,
    "phase27_17": "logs/phase27_17_real_broker_evidence.json",
    "phase27_18": "logs/phase27_18_historical_bidask.json",
    "phase27_19": "logs/phase27_19_commission_closure.json",
    "phase27_20": "logs/phase27_20_dataset_mapping_closure.json",
    "phase27_13": "logs/phase27_13_swap_policy.json",
    "phase27_14": "logs/phase27_14_slippage_model.json",
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
    return "UNKNOWN"


def load_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for key, rel in ARTIFACTS.items():
        data = _safe_load_json(root / rel)
        loaded[key] = data if isinstance(data, dict) else {}
    return loaded


def classify_historical_spread_coverage(
    *,
    tape_valid: bool,
    tape_bars: int,
    production_has_historical_bid_ask: bool,
) -> dict[str, str]:
    """A/B/C must not be conflated."""
    existence = PROVEN if tape_valid and tape_bars > 0 else BLOCKED
    dataset_coverage = PROVEN if production_has_historical_bid_ask else BLOCKED
    validation = PROVEN if production_has_historical_bid_ask and tape_valid else BLOCKED
    if tape_valid and tape_bars > 0 and not production_has_historical_bid_ask:
        dataset_coverage = BLOCKED
        validation = BLOCKED
    return {
        "A_historical_bid_ask_exists": existence,
        "B_full_canonical_dataset_spread": dataset_coverage,
        "C_cost_aware_validation_coverage": validation,
    }


def ev_eq_01_can_close(
    *,
    xauusd_exists: bool,
    xauusd_i_exists: bool,
    both_on_same_environment: bool,
    field_match: bool,
) -> dict[str, Any]:
    closable = bool(xauusd_exists and xauusd_i_exists and both_on_same_environment and field_match)
    return {
        "can_close": closable,
        "status": PROVEN if closable else BLOCKED,
        "evidence_status": "PROVEN" if closable else "NOT_PROVEN",
        "xauusd_absent_does_not_prove_equivalence": True,
        "xauusd_absent_does_not_prove_broker_wide_absence": True,
        "reason": (
            "EV-EQ-01 requires both symbols on the same Real terminal with critical-field MATCH. "
            "XAUUSD absent + XAUUSD_i present is not equivalence and is not broker-wide absence. "
            "Decision 1 (canonical XAUUSD_i) is POLICY, not EV-EQ-01 proof."
        ),
    }


def mapping_justified_from_filename_or_environment() -> bool:
    return False


def commission_verified(
    *,
    account_product_type: str | None,
    basis: str | None,
    effective_date: str | None,
    applicability_established: bool,
    observed_zero: bool,
) -> dict[str, Any]:
    missing = []
    if not account_product_type or str(account_product_type).upper() in {"", "UNKNOWN"}:
        missing.append("account_product_type")
    if not basis or str(basis).upper() in {"", "UNKNOWN"}:
        missing.append("basis")
    if not effective_date or str(effective_date).upper() in {"", "UNKNOWN"}:
        missing.append("effective_date_or_version")
    if not applicability_established:
        missing.append("applicability_established")
    verified = not missing and not observed_zero
    # observed zero never upgrades to verified even if other fields appear
    if observed_zero:
        verified = False
    return {
        "verified": verified,
        "status": "UNKNOWN / BLOCKED" if not verified else "VERIFIED_SCHEDULE",
        "classification": BLOCKED if not verified else PROVEN,
        "observed_zero_is_not_verified": True,
        "missing": missing,
    }


def swap_under_broker_rate_only(
    *,
    rates_present: bool,
    rollover_present: bool,
    historical_series: str,
) -> dict[str, Any]:
    series_unknown = str(historical_series or UNKNOWN).upper() in {"", "UNKNOWN", "NONE"}
    complete_requires_historical = True  # current evaluate_swap + availability_blocks_completeness
    return {
        "broker_rates": PROVEN if rates_present else UNKNOWN,
        "rollover_day": PROVEN if rollover_present else UNKNOWN,
        "historical_series": UNKNOWN if series_unknown else PROVEN,
        "policy": LOCKED_POLICY["DECISION_4"],
        "complete_requires_historical_series": complete_requires_historical,
        "broker_rate_only_blocks_completeness": availability_blocks_completeness(
            CostAvailability.BROKER_RATE_ONLY
        ),
        "synthesized_status": UNKNOWN if series_unknown else PROVEN,
    }


def slippage_under_modeled(
    *,
    realized_samples: int,
    statistically_sufficient: bool,
) -> dict[str, Any]:
    modeled_blocks = availability_blocks_completeness(CostAvailability.MODELED_PROXY)
    realized_ok = statistically_sufficient and realized_samples > 0
    return {
        "realized_samples": realized_samples,
        "modeled_proxy_documented": True,
        "assumptions": "base_slippage_pips=0.8 + session_hour multiplier; MT5 deviation ≠ slippage",
        "modeled_satisfies_complete_under_current_code": False,
        "lack_of_realized_blocks_complete": (not realized_ok) or modeled_blocks,
        "synthesized_status": PROVEN if realized_ok else UNKNOWN,
        "policy": LOCKED_POLICY["DECISION_5"],
    }


def classify_execution_model() -> dict[str, Any]:
    """Inspect current SimulatedBroker contract without changing it."""
    return {
        "status": UNKNOWN,
        "model": "full_fill_simulated",
        "why_unknown": (
            "Phase 27.15 evaluate_execution_model always returns UNKNOWN because "
            "SimulatedBroker assumes full fill and no realized execution tape exists."
        ),
        "kind": {
            "A_missing_required_evidence": True,
            "B_missing_documented_simulation_classification": True,
            "C_dependent_on_realized_execution_data": True,
        },
        "documentation_only": False,
        "note": (
            "The simulation contract is documented (full fill, fail-closed on UNKNOWN commission) "
            "but COMPLETE currently requires realized fills/partials. Treating the simulator as "
            "COMPLETE without that tape would weaken Decision 6."
        ),
        "evidence": "tradingbot/backtest/broker.py SimulatedBroker; logs/phase27_15_cost_completeness_gate.json",
    }


def _component(
    name: str,
    *,
    status: str,
    artifact: str,
    note: str,
    gate_artifact_status: str | None = None,
) -> dict[str, Any]:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid status {status} for {name}")
    return {
        "component": name,
        "status": status,
        "evidence_artifact": artifact,
        "gate_artifact_status": gate_artifact_status or status,
        "note": note,
    }


def build_evidence_matrix(arts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    p15 = arts["phase27_15"]
    p16 = arts["phase27_16"]
    p17 = arts["phase27_17"]
    p18 = arts["phase27_18"]
    p19 = arts["phase27_19"]
    p20 = arts["phase27_20"]
    p13 = arts["phase27_13"]
    p14 = arts["phase27_14"]

    tape = p18.get("tape") if isinstance(p18.get("tape"), dict) else {}
    tape_meta = tape.get("provenance") if isinstance(tape.get("provenance"), dict) else {}
    tape_bars = int(tape_meta.get("row_count") or 0)
    tape_valid = str(p18.get("evidence_status") or "") == "DATASET" and tape_bars > 0
    prod_bidask = bool((p18.get("inventory") or {}).get("historical_bid_ask_available"))
    spread_abc = classify_historical_spread_coverage(
        tape_valid=tape_valid,
        tape_bars=tape_bars,
        production_has_historical_bid_ask=prod_bidask,
    )

    xauusd_yes = str((p17.get("XAUUSD_status") or {}).get("existence") or "") == "YES"
    xauusd_i_yes = str((p17.get("XAUUSD_i_status") or {}).get("existence") or "") == "YES"
    ev = ev_eq_01_can_close(
        xauusd_exists=xauusd_yes,
        xauusd_i_exists=xauusd_i_yes,
        both_on_same_environment=bool((p17.get("ev_eq_01") or {}).get("both_on_same_environment")),
        field_match=False,
    )

    blocked_maps = int(p20.get("authorization_required_count") or 0)
    comm = p19.get("verified_schedule") if isinstance(p19.get("verified_schedule"), dict) else {}
    comm_eval = commission_verified(
        account_product_type=(p19.get("applicability_matrix") or {}).get("fields", {}).get("account_product_type"),
        basis=(p19.get("applicability_matrix") or {}).get("fields", {}).get("commission_basis"),
        effective_date=(p19.get("applicability_matrix") or {}).get("fields", {}).get("effective_date_or_version"),
        applicability_established=bool((p19.get("applicability_matrix") or {}).get("applicability_established")),
        observed_zero=str((p19.get("operator_deal_tape") or {}).get("classification"))
        == "OBSERVED_ZERO_NOT_PROVEN",
    )

    econ17 = (p17.get("economics") or {}).get("XAUUSD_i") if isinstance(p17.get("economics"), dict) else {}
    swap = swap_under_broker_rate_only(
        rates_present=econ17.get("swap_long") not in (None, "UNKNOWN")
        or (p13.get("observed_real_rates") or {}).get("swap_long") not in (None, "UNKNOWN"),
        rollover_present=econ17.get("swap_rollover3days") not in (None, "UNKNOWN")
        or (p13.get("observed_real_rates") or {}).get("swap_rollover3days") not in (None, "UNKNOWN"),
        historical_series=str(p13.get("historical_swap_series") or UNKNOWN),
    )
    slip = slippage_under_modeled(
        realized_samples=int((p14.get("classification") or {}).get("realized_sample_count") or 0),
        statistically_sufficient=bool(
            (p14.get("classification") or {}).get("statistically_sufficient_realized")
        ),
    )
    exe = classify_execution_model()
    p15_comp = p15.get("components") if isinstance(p15.get("components"), dict) else {}
    final_gate = str(p16.get("FINAL_GATE") or BLOCKED)

    components = {
        "symbol_binding": _component(
            "symbol_binding",
            status=BLOCKED,
            artifact="logs/phase27_20_dataset_mapping_closure.json",
            gate_artifact_status=str((p15_comp.get("symbol_binding") or {}).get("status") or BLOCKED),
            note=f"{blocked_maps} logical XAUUSD remain BLOCKED without explicit dataset_symbol_map.",
        ),
        "EV-EQ-01": _component(
            "EV-EQ-01",
            status=BLOCKED,
            artifact="logs/phase27_17_real_broker_evidence.json",
            gate_artifact_status="NOT_PROVEN",
            note=ev["reason"],
        ),
        "broker_economics": _component(
            "broker_economics",
            status=PARTIAL,
            artifact="logs/phase27_17_real_broker_evidence.json",
            gate_artifact_status=str((p15_comp.get("economics") or {}).get("status") or UNKNOWN),
            note=(
                "Fresh Real XAUUSD_i specs exist (27.17). 27.15 still classifies economics from 27.9 "
                f"as {str((p15_comp.get('economics') or {}).get('status') or UNKNOWN)}. "
                "Even with 27.17, EV-EQ-01 is NOT_PROVEN so COMPLETE is not earned."
            ),
        ),
        "dataset_provenance": _component(
            "dataset_provenance",
            status=PARTIAL,
            artifact="logs/phase27_20_dataset_mapping_closure.json",
            gate_artifact_status=str((p15_comp.get("dataset_provenance") or {}).get("status") or PARTIAL),
            note="Sidecars exist; cost fields incomplete; 0 COMPLETE datasets.",
        ),
        "historical_spread": _component(
            "historical_spread",
            status=BLOCKED,
            artifact="logs/phase27_18_historical_bidask.json",
            gate_artifact_status=str((p15_comp.get("spread") or {}).get("status") or BLOCKED),
            note=(
                f"A existence={spread_abc['A_historical_bid_ask_exists']} (bounded logs tape {tape_bars} M5 bars). "
                f"B dataset coverage={spread_abc['B_full_canonical_dataset_spread']}. "
                f"C validation={spread_abc['C_cost_aware_validation_coverage']}. "
                "Production parquets remain OHLC PROXY."
            ),
        ),
        "commission": _component(
            "commission",
            status=BLOCKED,
            artifact="logs/phase27_19_commission_closure.json",
            gate_artifact_status=str((p15_comp.get("commission") or {}).get("status") or BLOCKED),
            note="UNKNOWN / BLOCKED. 50 zeros remain OBSERVED_ZERO_NOT_PROVEN. No account-applicable schedule.",
        ),
        "swap": _component(
            "swap",
            status=UNKNOWN,
            artifact="logs/phase27_13_swap_policy.json + logs/phase27_17_real_broker_evidence.json",
            gate_artifact_status=str((p15_comp.get("swap") or {}).get("status") or UNKNOWN),
            note=(
                f"Rates {swap['broker_rates']}; rollover {swap['rollover_day']}; "
                f"historical series {swap['historical_series']}. "
                "BROKER_RATE_ONLY blocks COMPLETE under current code."
            ),
        ),
        "slippage": _component(
            "slippage",
            status=UNKNOWN,
            artifact="logs/phase27_14_slippage_model.json",
            gate_artifact_status=str((p15_comp.get("slippage") or {}).get("status") or UNKNOWN),
            note="MODELED_PROXY documented; 0 realized samples. MODELED does not satisfy COMPLETE.",
        ),
        "execution_model": _component(
            "execution_model",
            status=UNKNOWN,
            artifact=exe["evidence"],
            gate_artifact_status=str((p15_comp.get("execution_model") or {}).get("status") or UNKNOWN),
            note=exe["why_unknown"],
        ),
        "cost_completeness": _component(
            "cost_completeness",
            status=BLOCKED,
            artifact="logs/phase27_15_cost_completeness_gate.json",
            gate_artifact_status=BLOCKED,
            note="COMPLETE_COSTS_REQUIRED AND-gate is not COMPLETE. 0 COMPLETE datasets. FINAL_GATE BLOCKED.",
        ),
    }
    return {
        "components": components,
        "spread_coverage": spread_abc,
        "ev_eq_01": ev,
        "commission_eval": comm_eval,
        "swap_eval": swap,
        "slippage_eval": slip,
        "execution_eval": exe,
        "tape_bars": tape_bars,
        "tape_valid": tape_valid,
        "blocked_map_count": blocked_maps,
        "final_gate": final_gate if final_gate in ALLOWED_STATUSES or final_gate == "BLOCKED" else BLOCKED,
        "commission_display": comm.get("commission_status_display") or "UNKNOWN / BLOCKED",
    }


def build_blocker_table(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "blocker": "EV-EQ-01",
            "current_status": "NOT_PROVEN / BLOCKED",
            "why_blocked": "XAUUSD absent and XAUUSD_i present on one Real terminal is not equivalence.",
            "minimum_evidence_required": "Both symbols on the same Real terminal with critical-field MATCH.",
            "can_be_collected_from_current_real_terminal": "NO — XAUUSD is not in this catalog",
            "requires_operator_decision": "NO (Decision 1 already locked; does not close EV-EQ-01)",
            "requires_historical_data": "NO",
            "requires_code_change": "NO",
        },
        {
            "blocker": "symbol_binding / 30 logical XAUUSD",
            "current_status": BLOCKED,
            "why_blocked": "ONLY_WITH_EXPLICIT_DATASET_MAP; filename/sidecar label is not a map.",
            "minimum_evidence_required": "Explicit per-dataset or BacktestConfig dataset_symbol_map plus provenance.",
            "can_be_collected_from_current_real_terminal": "NO — mapping is authorization/provenance, not a tick download",
            "requires_operator_decision": "YES — authorize explicit maps or leave blocked",
            "requires_historical_data": "NO (unless proving dataset origin)",
            "requires_code_change": "NO",
        },
        {
            "blocker": "historical_spread dataset/validation coverage",
            "current_status": BLOCKED,
            "why_blocked": "82 M5 bars / one session prove existence only; production XAUUSD_i parquets are OHLC PROXY.",
            "minimum_evidence_required": "Historical Bid/Ask covering the canonical validation dataset range, stored as a bound tape (not live tick).",
            "can_be_collected_from_current_real_terminal": "PARTIAL — copy_ticks_range if broker retains ticks; 100k cap / weekend limits apply",
            "requires_operator_decision": "NO",
            "requires_historical_data": "YES",
            "requires_code_change": "NO (ingest later; do not convert OHLC)",
        },
        {
            "blocker": "commission VERIFIED_SCHEDULE",
            "current_status": "UNKNOWN / BLOCKED",
            "why_blocked": "Account/product type, basis, and applicability missing. Observed zeros ≠ schedule.",
            "minimum_evidence_required": "Account-applicable schedule with product type, basis, currency, effective date.",
            "can_be_collected_from_current_real_terminal": "NO — read-only account identity is not a schedule",
            "requires_operator_decision": "YES — obtain/confirm product type and applicable schedule",
            "requires_historical_data": "NO",
            "requires_code_change": "NO",
        },
        {
            "blocker": "swap historical series",
            "current_status": UNKNOWN,
            "why_blocked": "Rates/rollover are snapshots. COMPLETE currently requires a historical series; BROKER_RATE_ONLY blocks completeness.",
            "minimum_evidence_required": "Historical swap series, or an explicit later policy change (not proposed).",
            "can_be_collected_from_current_real_terminal": "NO — a single attach is not a series",
            "requires_operator_decision": "NO (Decision 4 already locked)",
            "requires_historical_data": "YES (for COMPLETE under current code)",
            "requires_code_change": "NO (changing this to COMPLETE from rates would weaken the gate)",
        },
        {
            "blocker": "slippage realized distribution",
            "current_status": UNKNOWN,
            "why_blocked": "MODELED_PROXY is documented; 0 requested-vs-fill samples. MODELED ≠ COMPLETE.",
            "minimum_evidence_required": "Statistically sufficient requested-vs-fill pairs.",
            "can_be_collected_from_current_real_terminal": "PARTIAL — only if deal history contains usable request vs fill",
            "requires_operator_decision": "NO (Decision 5 already locked)",
            "requires_historical_data": "YES (realized tape)",
            "requires_code_change": "NO",
        },
        {
            "blocker": "execution_model",
            "current_status": UNKNOWN,
            "why_blocked": "SimulatedBroker full-fill is not a realized execution tape; 27.15 requires realized fills for COMPLETE.",
            "minimum_evidence_required": "Realized fill/partial tape, or a later documented simulation-contract path (not added here).",
            "can_be_collected_from_current_real_terminal": "PARTIAL — live/history fills only if collected as an execution tape",
            "requires_operator_decision": "NO",
            "requires_historical_data": "YES for realized COMPLETE",
            "requires_code_change": "NO in this phase; classification-only path would be a later decision",
        },
        {
            "blocker": "cost_completeness / FINAL_GATE",
            "current_status": BLOCKED,
            "why_blocked": "COMPLETE_COSTS_REQUIRED AND of all components is not COMPLETE.",
            "minimum_evidence_required": "Every required component COMPLETE without weakening the AND.",
            "can_be_collected_from_current_real_terminal": "NO — multiple independent gaps remain",
            "requires_operator_decision": "YES for maps and commission; NO for inventing COMPLETE",
            "requires_historical_data": "YES (spread coverage, swap series, realized slippage/execution)",
            "requires_code_change": "NO",
        },
    ]


def identify_documentation_vs_evidence(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "item": "27.15/27.16 economics still cite Phase 27.9",
            "kind": "DOCUMENTATION_OR_CLASSIFICATION_LAG",
            "auto_fixed": False,
            "would_become_complete_if_reclassified": False,
            "note": (
                "27.17 collected fresh Real XAUUSD_i economics. Re-pointing 27.15 would likely move "
                "economics UNKNOWN→PARTIAL, not COMPLETE (EV-EQ-01 still NOT_PROVEN). Not auto-fixed."
            ),
        },
        {
            "item": "27.8 'evidence still missing' still lists fresh Real and M5 tape as MISSING",
            "kind": "STALE_LOCKED_SNAPSHOT",
            "auto_fixed": False,
            "would_become_complete_if_reclassified": False,
            "note": "27.8 is a locked snapshot. 27.17/27.18 closed those items at sample/fresh-attach level only.",
        },
        {
            "item": "execution_model UNKNOWN vs documented SimulatedBroker contract",
            "kind": "MIXED_CLASSIFICATION_AND_EVIDENCE",
            "auto_fixed": False,
            "would_become_complete_if_reclassified": False,
            "note": (
                "A documented full-fill simulator exists, but COMPLETE currently requires realized fills. "
                "Reclassifying simulation as COMPLETE would weaken Decision 6. Not auto-fixed."
            ),
        },
        {
            "item": "27.18 logs tape vs 27.15 spread BLOCKED",
            "kind": "NOT_DOCUMENTATION — COVERAGE GAP",
            "auto_fixed": False,
            "would_become_complete_if_reclassified": False,
            "note": "Existence is PROVEN. Dataset/validation coverage remains BLOCKED. Must not conflate A with B/C.",
        },
    ]


def run_phase27_21_evidence_synthesis(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    arts = load_artifacts(root)
    matrix = build_evidence_matrix(arts)
    blockers = build_blocker_table(matrix)
    docs_vs_ev = identify_documentation_vs_evidence(matrix)
    p17 = arts["phase27_17"]
    p18 = arts["phase27_18"]
    p20 = arts["phase27_20"]
    p15 = arts["phase27_15"]
    p16 = arts["phase27_16"]

    mapping_still_blocked = int(p20.get("authorization_required_count") or 0) == 30
    no_new_maps = mapping_justified_from_filename_or_environment() is False
    final_gate = str(p16.get("FINAL_GATE") or BLOCKED)
    cost_ready = bool(p15.get("cost_ready_for_validation")) if "cost_ready_for_validation" in p15 else False

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.21",
        "status": "PASS",
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator_policy": dict(LOCKED_POLICY),
        "policy_is_not_evidence": True,
        "evidence_matrix": matrix["components"],
        "spread_coverage": matrix["spread_coverage"],
        "ev_eq_01": matrix["ev_eq_01"],
        "what_27_17_closed": {
            "fresh_real_attach": str(p17.get("attach_status") or UNKNOWN),
            "XAUUSD_i_existence": str((p17.get("XAUUSD_i_status") or {}).get("existence") or UNKNOWN),
            "XAUUSD_existence": str((p17.get("XAUUSD_status") or {}).get("existence") or UNKNOWN),
            "fresh_xauusd_i_economics": True,
            "ev_eq_01": "NOT_PROVEN",
            "did_not_close": ["EV-EQ-01", "commission", "dataset maps", "FINAL_GATE"],
        },
        "what_27_18_closed": {
            "historical_bid_ask_existence": matrix["spread_coverage"]["A_historical_bid_ask_exists"],
            "tape_bars": matrix["tape_bars"],
            "scope": "bounded logs-only validation window; not production dataset rewrite",
            "did_not_close": [
                "full canonical dataset spread",
                "cost-aware validation coverage",
                "FINAL_GATE",
            ],
        },
        "dataset_mapping": {
            "logical_xauusd_blocked": int(p20.get("authorization_required_count") or 0),
            "maps_inserted": bool(p20.get("maps_inserted")),
            "filename_or_environment_justifies_map": False,
            "remain_blocked": mapping_still_blocked,
        },
        "commission": matrix["commission_eval"],
        "swap": matrix["swap_eval"],
        "slippage": matrix["slippage_eval"],
        "execution_model": matrix["execution_eval"],
        "blocker_table": blockers,
        "documentation_vs_evidence": docs_vs_ev,
        "cost_ready_for_validation": cost_ready,
        "FINAL_GATE": final_gate,
        "gates_weakened": False,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "mt5_restarted": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "sizing_modified": False,
            "rr_modified": False,
            "ml_modified": False,
            "backtest_behavior_modified": False,
            "phase_27_22_started": False,
        },
        "deferred": ["Phase 27.22+ — not started"],
    }

    required = (
        final_gate == BLOCKED,
        not cost_ready,
        not payload["gates_weakened"],
        mapping_still_blocked,
        no_new_maps,
        matrix["spread_coverage"]["A_historical_bid_ask_exists"] == PROVEN,
        matrix["spread_coverage"]["B_full_canonical_dataset_spread"] == BLOCKED,
        matrix["spread_coverage"]["C_cost_aware_validation_coverage"] == BLOCKED,
        matrix["ev_eq_01"]["can_close"] is False,
        matrix["commission_eval"]["verified"] is False,
        matrix["components"]["cost_completeness"]["status"] == BLOCKED,
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2721_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_known_unknowns(root, payload)
    return payload


def run_phase27_21_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_21_evidence_synthesis(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    comps = payload["evidence_matrix"]
    rows = [
        "| Component | Status | Evidence artifact |",
        "|---|---|---|",
    ]
    for name, row in comps.items():
        rows.append(
            f"| `{name}` | **{row['status']}** | `{row['evidence_artifact']}` |"
        )
    matrix_tbl = "\n".join(rows)
    spread = payload["spread_coverage"]
    blockers = [
        "| BLOCKER | CURRENT STATUS | WHY BLOCKED | MINIMUM EVIDENCE | FROM CURRENT REAL TERMINAL? | OPERATOR DECISION? | HISTORICAL DATA? | CODE CHANGE? |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in payload["blocker_table"]:
        blockers.append(
            "| {blocker} | {current_status} | {why_blocked} | {minimum_evidence_required} | "
            "{can_be_collected_from_current_real_terminal} | {requires_operator_decision} | "
            "{requires_historical_data} | {requires_code_change} |".format(**b)
        )
    blocker_tbl = "\n".join(blockers)
    docs = "\n".join(
        f"- **{d['item']}** — `{d['kind']}` (not auto-fixed): {d['note']}"
        for d in payload["documentation_vs_evidence"]
    )
    w17 = payload["what_27_17_closed"]
    w18 = payload["what_27_18_closed"]
    md = f"""# Phase 27.21 — Evidence Synthesis & Remaining Blocker Audit

**Status:** {payload['status']}  
**FINAL_GATE:** **{payload['FINAL_GATE']}**  
**Artifact:** `{PHASE2721_JSON}`

Audit/synthesis only. Gates were not weakened. Strategy, RiskGate, execution, sizing, RR, and ML were not changed. No MT5 collection.

## Locked policy (not evidence)

| # | POLICY |
|---|---|
| 1 | Canonical gold = `XAUUSD_i` |
| 2 | Logical XAUUSD = `ONLY_WITH_EXPLICIT_DATASET_MAP` |
| 3 | Commission = `VERIFIED_SCHEDULE` |
| 4 | Swap = `BROKER_RATE_ONLY` |
| 5 | Slippage = `MODELED` |
| 6 | Validation = `COMPLETE_COSTS_REQUIRED` |

## 1. Current evidence matrix

{matrix_tbl}

## 2. What Phase 27.17 actually closed

Fresh Real attach `{w17['fresh_real_attach']}` on LiteFinance-MT5-Live. `XAUUSD_i` existence `{w17['XAUUSD_i_existence']}`. `XAUUSD` existence `{w17['XAUUSD_existence']}`. Fresh `XAUUSD_i` economics collected. **EV-EQ-01 remains NOT_PROVEN.** Did not close commission, maps, or FINAL_GATE.

## 3. What Phase 27.18 actually closed

Historical Bid/Ask **existence** = `{spread['A_historical_bid_ask_exists']}` (`{w18['tape_bars']}` M5 bars; logs-only bounded window).

| Question | Status |
|---|---|
| A. Historical Bid/Ask exists | **{spread['A_historical_bid_ask_exists']}** |
| B. Historical spread for the entire canonical dataset | **{spread['B_full_canonical_dataset_spread']}** |
| C. Cost-aware validation of the production research dataset | **{spread['C_cost_aware_validation_coverage']}** |

A must not be treated as B or C.

## 4. EV-EQ-01

`XAUUSD` absent and `XAUUSD_i` present on this Real catalog does **not** prove equivalence and does **not** prove broker-wide absence. Decision 1 does not close EV-EQ-01. **NOT_PROVEN / BLOCKED.**

## 5. Dataset mapping

No new provenance justifies an explicit map. Filename, environment resolution, and broker-symbol similarity were not used. **30 logical XAUUSD remain BLOCKED.**

## 6. Commission

Still **UNKNOWN / BLOCKED**. 50 gold zeros remain `OBSERVED_ZERO_NOT_PROVEN`. `commission_per_lot=0.0` is not `ZERO`.

## 7. Swap (`BROKER_RATE_ONLY`)

Broker rates **PROVEN** (snapshot). Rollover day **PROVEN** (`3`). Historical series **UNKNOWN**. Current COMPLETE contract requires a historical series; `BROKER_RATE_ONLY` blocks completeness. Series was not synthesized.

## 8. Slippage (`MODELED`)

Realized samples = `0`. MODELED_PROXY is documented (`0.8` pips + session multiplier). Under current code, modeled slippage does **not** make COMPLETE. Lack of realized data **does** block COMPLETE.

## 9. Execution model

`SimulatedBroker` assumes full fill and fail-closes on UNKNOWN commission. Status remains **UNKNOWN** because 27.15 requires a realized execution tape for COMPLETE. This is mixed: documented simulation contract **and** missing realized fills. Not reclassified.

## 10. Minimum remaining evidence

{blocker_tbl}

## 11. Documentation / classification vs evidence

{docs}

## Production

**BLOCKED.** `COST_READY_FOR_VALIDATION` = `{payload['cost_ready_for_validation']}`. FINAL_GATE remains **{payload['FINAL_GATE']}**. Phase 27.22+ not started.

## Next

STOP after Phase 27.21.
"""
    (root / PHASE2721_MD).write_text(md, encoding="utf-8")


def _update_known_unknowns(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.21 evidence synthesis:** `{PHASE2721_JSON}` — FINAL_GATE remains BLOCKED"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.20 dataset mapping:** `logs/phase27_20_dataset_mapping_closure.json`",
            "**Phase 27.20 dataset mapping:** `logs/phase27_20_dataset_mapping_closure.json`  \n" + pointer,
        )
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
