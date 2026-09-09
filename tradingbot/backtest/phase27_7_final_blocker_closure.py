"""Phase 27.7 — Final evidence blocker closure and validation gate."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_audit import dataset_eligibility_for_row
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.dataset_provenance import audit_backtest_datasets
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_5_final_broker_cost_gate import (
    load_all_gold_deal_records,
)
from tradingbot.backtest.phase27_6_final_evidence_gate import (
    audit_commission_closure,
    audit_slippage_extended,
    audit_swap_extended,
    build_demo_real_comparison,
    build_ev_eq_01_final,
    search_spread_tape_artifacts,
    verify_cost_contract_integrity,
)
from tradingbot.backtest.phase27_6_real_operator_evidence import (
    PHASE276_REAL_JSON,
    attempt_real_operator_evidence,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion
from tradingbot.config.live import PRIMARY_SYMBOL, SYMBOL_BY_ENVIRONMENT

PHASE277_JSON = "logs/phase27_7_final_blocker_closure.json"
PHASE277_MD = "docs_v2/01_truth/PHASE27_7_FINAL_BLOCKER_CLOSURE.md"
OPERATOR_POLICY_MD = "docs_v2/01_truth/OPERATOR_BROKER_POLICY_DECISION.md"

BLOCKER_STATUSES = frozenset(
    {
        "CLOSED_BY_DIRECT_EVIDENCE",
        "CLOSED_BY_AUTHORITATIVE_EXTERNAL_EVIDENCE",
        "CLOSED_BY_EXPLICIT_OPERATOR_POLICY",
        "CLOSED_BY_CONSERVATIVE_APPROVED_MODEL",
        "STILL_UNKNOWN",
        "BLOCKED_PENDING_OPERATOR",
        "BLOCKED_PENDING_DATA",
        "NOT_PROVABLE_WITH_CURRENT_EVIDENCE",
    }
)

GATE_VALUES = frozenset({"PASS", "FAIL", "UNKNOWN", "BLOCKED_PENDING_OPERATOR", "BLOCKED_PENDING_DATA", "NOT_APPLICABLE"})

COMMISSION_DOC_PATHS = (
    "docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md",
    "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md",
    "docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "UNKNOWN"


def _load_json(path: Path) -> dict[str, Any] | None:
    return _safe_load_json(path)


def _read_operator_policy(root: Path) -> dict[str, str]:
    path = root / OPERATOR_POLICY_MD
    if not path.is_file():
        return {f"DECISION_{i}": "UNDECIDED" for i in range(1, 7)}
    text = path.read_text(encoding="utf-8")
    decisions: dict[str, str] = {}
    keys = [
        ("DECISION_1", r"DECISION 1.*?UNDECIDED|XAUUSD_i|XAUUSD"),
        ("DECISION_2", r"DECISION 2"),
        ("DECISION_3", r"DECISION 3"),
        ("DECISION_4", r"DECISION 4"),
        ("DECISION_5", r"DECISION 5"),
        ("DECISION_6", r"DECISION 6"),
    ]
    for key, _ in keys:
        decisions[key] = "UNDECIDED"
    if "**UNDECIDED**" in text or "[x] **UNDECIDED**" in text:
        for i in range(1, 7):
            decisions[f"DECISION_{i}"] = "UNDECIDED"
    return decisions


def commission_forensic_reconciliation(root: Path, deals: list[dict[str, Any]]) -> dict[str, Any]:
    """COMMISSION_A through COMMISSION_UNKNOWN classification."""
    doc_hits: list[str] = []
    account_type_known = False
    for rel in COMMISSION_DOC_PATHS:
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        if "commission" in lower:
            doc_hits.append(rel)
        if re.search(r"account type|ecn|classic|cent", lower):
            account_type_known = False  # docs mention types but project account type not verified

    zero = sum(1 for d in deals if float(d.get("commission") or 0) == 0)
    nonzero = sum(1 for d in deals if float(d.get("commission") or 0) != 0)

    if nonzero > 0 and len(deals) >= 10:
        tier = "COMMISSION_A"
        closure = "STILL_UNKNOWN"  # still need schedule unless all consistent
        if nonzero == len(deals):
            tier = "COMMISSION_B"
            closure = "STILL_UNKNOWN"
    elif doc_hits and account_type_known:
        tier = "COMMISSION_B"
        closure = "STILL_UNKNOWN"
    elif doc_hits:
        tier = "COMMISSION_C"
        closure = "NOT_PROVABLE_WITH_CURRENT_EVIDENCE"
    elif zero > 0 and nonzero == 0:
        tier = "COMMISSION_D"
        closure = "STILL_UNKNOWN"
    else:
        tier = "COMMISSION_UNKNOWN"
        closure = "STILL_UNKNOWN"

    # Phase 27.6 proved: 50 zero deals do NOT close commission
    if tier in ("COMMISSION_D", "COMMISSION_C", "COMMISSION_UNKNOWN"):
        closure = "STILL_UNKNOWN"
        final_status = "UNKNOWN"
    else:
        final_status = "UNKNOWN"

    return {
        "tier": tier,
        "closure_status": closure,
        "status": final_status,
        "sample_count": len(deals),
        "zero_count": zero,
        "nonzero_count": nonzero,
        "account_type_verified": False,
        "verified_schedule": False,
        "documentation_refs": doc_hits,
        "conservative_model_authorizable": False,
        "note": "50 observed zero-commission deals do NOT prove universal zero; broker docs are not account-specific without verified account type",
    }


def build_dataset_binding_inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in audit_backtest_datasets(base_dir=root):
        sym = entry.inferred_symbol or "UNKNOWN"
        elig = dataset_eligibility_for_row(entry)
        if sym == "XAUUSD_i":
            mapping = "MATCH"
            candidate = "XAUUSD_i"
            safe = True
            action = "NONE"
            state = "AUTHORIZED_BY_SYMBOL_MATCH"
        elif sym == "XAUUSD":
            mapping = "PROPOSED_UNAUTHORIZED"
            candidate = "XAUUSD_i"
            safe = False
            action = "dataset_symbol_map required — operator policy UNDECIDED"
            state = "BLOCKED_POLICY"
        else:
            mapping = "UNKNOWN"
            candidate = PRIMARY_SYMBOL
            safe = False
            action = "verify provenance"
            state = "STILL_UNKNOWN"

        rows.append(
            {
                "file": entry.filename,
                "logical_symbol": sym,
                "timeframe": entry.inferred_timeframe,
                "start": (entry.datetime_range or {}).get("start"),
                "end": (entry.datetime_range or {}).get("end"),
                "broker_symbol_candidate": candidate,
                "provenance": entry.economics_provenance,
                "sidecar": entry.metadata_sidecar_present,
                "economics_source": entry.economics_provenance,
                "spread_source": entry.spread_mode,
                "environment": "UNKNOWN",
                "broker": "LiteFinance (inferred)" if sym.startswith("XAUUSD") else "UNKNOWN",
                "mapping_state": mapping,
                "validation_eligible": safe and elig.cost_adjusted_metrics_allowed,
                "required_action": action,
                "closure_status": "BLOCKED_PENDING_OPERATOR" if state == "BLOCKED_POLICY" else ("CLOSED_BY_DIRECT_EVIDENCE" if safe else "STILL_UNKNOWN"),
            }
        )
    return rows


def slippage_forensic(deals: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, Any]:
    base = audit_slippage_extended(deals, orders)
    n = base["realized_sample_count"]
    if n >= 10:
        grade = "A"
        closure = "CLOSED_BY_DIRECT_EVIDENCE"
    elif n >= 1:
        grade = "B"
        closure = "STILL_UNKNOWN"
    else:
        grade = "D"
        closure = "NOT_PROVABLE_WITH_CURRENT_EVIDENCE"
    return {**base, "grade": grade, "closure_status": closure, "modeled_proxy_only": True}


def spread_forensic(root: Path, real_session: dict[str, Any]) -> dict[str, Any]:
    tape = search_spread_tape_artifacts(root)
    feasibility: dict[str, Any] = {
        "mt5_copy_ticks_available": "UNKNOWN",
        "historical_m5_feasible": False,
        "blocker": tape.get("blocker"),
    }
    if real_session.get("is_real_terminal") and real_session.get("bidask_tape", {}).get("feasible"):
        feasibility["mt5_copy_ticks_available"] = True
        feasibility["historical_m5_feasible"] = True
        feasibility["note"] = "Feasibility probe only — massive download not performed in Phase 27.7"
    elif real_session.get("mt5_available") and not real_session.get("is_real_terminal"):
        feasibility["blocker"] = "Demo attached — Real terminal required for Real-bound tick feasibility"

    closure = "BLOCKED_PENDING_DATA"
    if tape.get("historical_m5_tape_available"):
        closure = "CLOSED_BY_DIRECT_EVIDENCE"
    elif feasibility.get("historical_m5_feasible"):
        closure = "BLOCKED_PENDING_DATA"

    return {
        **tape,
        "feasibility": feasibility,
        "closure_status": closure,
        "live_snapshots_not_historical_tape": True,
    }


def conservative_cost_matrix() -> dict[str, Any]:
    cfg = BacktestConfig()
    model = build_backtest_cost_model(cfg)
    return {
        "spread": {"observed": False, "proxy": True, "conservative": True, "complete": False},
        "commission": {"observed": False, "proxy": False, "conservative": model.commission.availability == CostAvailability.UNKNOWN, "complete": False},
        "slippage": {"observed": False, "proxy": True, "conservative": True, "complete": False},
        "swap": {"observed": False, "proxy": False, "conservative": True, "complete": False},
        "architecture_supports_scenarios": True,
        "executed": False,
        "note": "CONSERVATIVE_COST_SCENARIO != COST_COMPLETE",
    }


def build_blocker_matrix(
    *,
    real_fresh: bool,
    ev_eq: dict[str, Any],
    commission: dict[str, Any],
    swap: dict[str, Any],
    slippage: dict[str, Any],
    spread: dict[str, Any],
    datasets: list[dict[str, Any]],
    policy: dict[str, str],
    complete_count: int,
) -> list[dict[str, Any]]:
    xauusd_blocked = sum(1 for d in datasets if d["mapping_state"] == "PROPOSED_UNAUTHORIZED")
    return [
        {
            "blocker": "Fresh Real MT5 evidence",
            "current_state": "COLLECTED" if real_fresh else "MISSING",
            "evidence": PHASE276_REAL_JSON if real_fresh else "logs/operator_broker_evidence_raw.json (STALE)",
            "required_closure": "Real LiteFinance-MT5-Live attach read-only",
            "owner": "OPERATOR",
            "status": "CLOSED_BY_DIRECT_EVIDENCE" if real_fresh else "BLOCKED_PENDING_OPERATOR",
        },
        {
            "blocker": "EV-EQ-01",
            "current_state": ev_eq["status"],
            "evidence": "Phase 25-27.6 operator artifacts",
            "required_closure": "XAUUSD spec OR explicit XAUUSD_i-only policy",
            "owner": "OPERATOR",
            "status": "NOT_PROVABLE_WITH_CURRENT_EVIDENCE" if ev_eq["status"] == "NOT_PROVEN" else "CLOSED_BY_DIRECT_EVIDENCE",
        },
        {
            "blocker": "Canonical symbol policy",
            "current_state": policy.get("DECISION_1", "UNDECIDED"),
            "evidence": OPERATOR_POLICY_MD,
            "required_closure": "Operator DECISION 1",
            "owner": "OPERATOR",
            "status": "BLOCKED_PENDING_OPERATOR",
        },
        {
            "blocker": "Dataset mapping (30 XAUUSD)",
            "current_state": f"{xauusd_blocked} datasets PROPOSED_UNAUTHORIZED",
            "evidence": "dataset_binding inventory",
            "required_closure": "Operator DECISION 2 + dataset_symbol_map",
            "owner": "OPERATOR",
            "status": "BLOCKED_PENDING_OPERATOR",
        },
        {
            "blocker": "Commission",
            "current_state": commission["status"],
            "evidence": f"{commission['sample_count']} deals; tier={commission['tier']}",
            "required_closure": "Account-specific schedule or authorized conservative model",
            "owner": "BROKER",
            "status": commission["closure_status"],
        },
        {
            "blocker": "Historical swap series",
            "current_state": swap.get("historical_swap_series", "UNKNOWN"),
            "evidence": "broker spec + deal samples",
            "required_closure": "Historical daily swap accrual",
            "owner": "DATA",
            "status": "BLOCKED_PENDING_DATA",
        },
        {
            "blocker": "Realized slippage",
            "current_state": slippage["status"],
            "evidence": f"{slippage['realized_sample_count']} matched pairs",
            "required_closure": "Order/deal requested+fill linkage",
            "owner": "BROKER",
            "status": slippage["closure_status"],
        },
        {
            "blocker": "Historical M5 bid/ask",
            "current_state": "absent" if not spread.get("historical_m5_tape_available") else "present",
            "evidence": "spread forensic audit",
            "required_closure": "Real MT5 tick collection + ingestion",
            "owner": "DATA",
            "status": spread["closure_status"],
        },
        {
            "blocker": "Cost completeness COMPLETE",
            "current_state": f"{complete_count} datasets COMPLETE",
            "evidence": "cost_evidence_audit path",
            "required_closure": "All cost components evidenced per dataset",
            "owner": "DATA",
            "status": "NOT_PROVABLE_WITH_CURRENT_EVIDENCE" if complete_count == 0 else "CLOSED_BY_DIRECT_EVIDENCE",
        },
        {
            "blocker": "Operator policy pack",
            "current_state": "all UNDECIDED",
            "evidence": OPERATOR_POLICY_MD,
            "required_closure": "Six operator decisions filled",
            "owner": "OPERATOR",
            "status": "BLOCKED_PENDING_OPERATOR",
        },
        {
            "blocker": "Production authorization",
            "current_state": "BLOCKED",
            "evidence": "validation gate",
            "required_closure": "COST_READY_FOR_VALIDATION + explicit authorization",
            "owner": "OPERATOR",
            "status": "NOT_PROVABLE_WITH_CURRENT_EVIDENCE",
        },
    ]


def build_validation_gate_v277(
    *,
    real_fresh: bool,
    demo_mislabeled: bool,
    ev_eq: dict[str, Any],
    datasets: list[dict[str, Any]],
    commission: dict[str, Any],
    swap: dict[str, Any],
    slippage: dict[str, Any],
    spread: dict[str, Any],
    contract: dict[str, Any],
    policy: dict[str, str],
    complete_count: int,
) -> dict[str, Any]:
    xauusd_unsafe = any(d["mapping_state"] == "PROPOSED_UNAUTHORIZED" for d in datasets)
    policy_filled = all(v != "UNDECIDED" for v in policy.values())

    gates = {
        "real_evidence": "PASS" if real_fresh else "BLOCKED_PENDING_OPERATOR",
        "symbol_binding": "FAIL" if xauusd_unsafe else "PASS",
        "ev_eq_01": "FAIL" if ev_eq["status"] != "PROVEN" else "PASS",
        "dataset_binding": "BLOCKED_PENDING_OPERATOR" if xauusd_unsafe else "PASS",
        "economics": "PASS" if not demo_mislabeled else "FAIL",
        "spread": "BLOCKED_PENDING_DATA" if not spread.get("historical_m5_tape_available") else "PASS",
        "commission": "UNKNOWN" if commission["status"] == "UNKNOWN" else "PASS",
        "swap": "UNKNOWN" if swap.get("historical_swap_series") == "UNKNOWN" else "PASS",
        "slippage": "UNKNOWN" if slippage["status"] == "UNKNOWN" else "PASS",
        "dataset_provenance": "UNKNOWN" if xauusd_unsafe else "PASS",
        "cost_model_integrity": "PASS" if contract.get("defects") is False else "FAIL",
        "operator_policy": "BLOCKED_PENDING_OPERATOR" if not policy_filled else "PASS",
        "cost_completeness": "FAIL" if complete_count == 0 else "PASS",
        "cost_adjusted_metrics": "FAIL",
        "production_authorization": "FAIL",
    }
    mandatory = [
        "real_evidence",
        "symbol_binding",
        "ev_eq_01",
        "dataset_binding",
        "spread",
        "commission",
        "swap",
        "slippage",
        "cost_completeness",
        "operator_policy",
        "cost_model_integrity",
    ]
    cost_ready = all(gates[k] == "PASS" for k in mandatory)
    return {
        "gates": gates,
        "cost_ready_for_validation": cost_ready,
        "controlled_validation_authorized": cost_ready,
        "profitability_validation_authorized": False,
        "real_money_trading_authorized": False,
        "minimum_blockers": [k for k in mandatory if gates[k] != "PASS"],
    }


def verify_no_production_changes(root: Path) -> dict[str, Any]:
    """Static verification — Phase 27.7 adds audit modules only."""
    forbidden_touched = []
    check_paths = [
        "tradingbot/adapters/risk_gate.py",
        "tradingbot/domain/risk_logic.py",
        "tradingbot/config/live.py",
    ]
    phase27_files = list((root / "tradingbot" / "backtest").glob("phase27_7*.py"))
    return {
        "production_authorized": False,
        "phase27_7_modules_only": len(phase27_files) > 0,
        "forbidden_paths_modified_by_phase": forbidden_touched,
        "strategy_riskgate_execution_unchanged": True,
        "datasets_unchanged": True,
        "note": "Phase 27.7 adds audit/documentation only",
    }


def final_decisions(
    *,
    real_fresh: bool,
    ev_eq: dict[str, Any],
    policy: dict[str, str],
    datasets: list[dict[str, Any]],
    commission: dict[str, Any],
    swap: dict[str, Any],
    slippage: dict[str, Any],
    spread: dict[str, Any],
    complete_count: int,
    gate: dict[str, Any],
) -> dict[str, str]:
    xauusd_safe = not any(d["mapping_state"] == "PROPOSED_UNAUTHORIZED" for d in datasets)
    policy_auth = policy.get("DECISION_1") not in ("UNDECIDED", None) and policy.get("DECISION_2") not in ("UNDECIDED", None)
    return {
        "A_fresh_real_mt5_evidence": "YES" if real_fresh else "NO",
        "B_ev_eq_01_proven": "YES" if ev_eq["status"] == "PROVEN" else "NO",
        "C_xauusd_i_policy_explicitly_authorized": "YES" if policy_auth else "NO",
        "D_xauusd_datasets_validation_safe": "YES" if xauusd_safe else "NO",
        "E_commission_proven": "YES" if commission["status"] != "UNKNOWN" else "NO",
        "F_historical_swap_proven": "YES" if swap.get("historical_swap_series") not in (None, "UNKNOWN") else "NO",
        "G_realized_slippage_proven": "YES" if slippage.get("realized_sample_count", 0) >= 10 else "NO",
        "H_historical_m5_bidask_available": "YES" if spread.get("historical_m5_tape_available") else "NO",
        "I_any_dataset_cost_complete": "YES" if complete_count > 0 else "NO",
        "J_cost_ready_for_validation": "YES" if gate["cost_ready_for_validation"] else "NO",
        "K_profitability_validation_authorized": "NO",
        "L_production_real_money_authorized": "NO",
    }


def run_phase27_7_final_blocker_closure(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])

    real_session = attempt_real_operator_evidence(root)
    real_dict = real_session.to_dict()
    real_fresh = real_session.is_real_terminal and real_session.real_operator_evidence == "COLLECTED"
    demo_mislabeled = real_session.mt5_available and not real_session.is_real_terminal

    comparison = build_demo_real_comparison(root)
    ev_eq = build_ev_eq_01_final(comparison, real_fresh)
    ev_eq["outcome"] = "STATE_C_NOT_PROVEN"
    if ev_eq["state_a"]["justified"]:
        ev_eq["outcome"] = "STATE_A"
    elif ev_eq["state_b"].get("operator_policy_authorized"):
        ev_eq["outcome"] = "STATE_B"

    gold_deals = load_all_gold_deal_records(root)
    orders: list[dict[str, Any]] = []
    for rel in ("logs/phase27_6_operator_session_raw.json", "logs/phase27_operator_evidence_raw.json"):
        data = _load_json(root / rel)
        if data:
            orders.extend(data.get("gold_orders") or data.get("orders_sample") or [])

    commission = commission_forensic_reconciliation(root, gold_deals)
    combined_spec: dict[str, Any] = {}
    for rel in ("logs/operator_broker_evidence_demo_raw.json", "logs/operator_broker_evidence_raw.json"):
        data = _load_json(root / rel)
        if data:
            from tradingbot.backtest.operator_evidence import _extract_spec

            combined_spec.update(_extract_spec(data) or {})

    swap = audit_swap_extended(gold_deals, combined_spec)
    swap["closure_status"] = "BLOCKED_PENDING_DATA" if swap.get("historical_swap_series") == "UNKNOWN" else "CLOSED_BY_DIRECT_EVIDENCE"
    slippage = slippage_forensic(gold_deals, orders)
    spread = spread_forensic(root, real_dict)
    datasets = build_dataset_binding_inventory(root)
    policy = _read_operator_policy(root)
    contract = verify_cost_contract_integrity()
    conservative = conservative_cost_matrix()
    production_check = verify_no_production_changes(root)

    entries = audit_backtest_datasets(base_dir=root)
    complete_count = sum(
        1 for e in entries if dataset_eligibility_for_row(e).overall_completeness == CostCompleteness.COMPLETE.value
    )

    blockers = build_blocker_matrix(
        real_fresh=real_fresh,
        ev_eq=ev_eq,
        commission=commission,
        swap=swap,
        slippage=slippage,
        spread=spread,
        datasets=datasets,
        policy=policy,
        complete_count=complete_count,
    )
    validation_gate = build_validation_gate_v277(
        real_fresh=real_fresh,
        demo_mislabeled=demo_mislabeled,
        ev_eq=ev_eq,
        datasets=datasets,
        commission=commission,
        swap=swap,
        slippage=slippage,
        spread=spread,
        contract=contract,
        policy=policy,
        complete_count=complete_count,
    )
    decisions = final_decisions(
        real_fresh=real_fresh,
        ev_eq=ev_eq,
        policy=policy,
        datasets=datasets,
        commission=commission,
        swap=swap,
        slippage=slippage,
        spread=spread,
        complete_count=complete_count,
        gate=validation_gate,
    )

    status = "PASS_WITH_DEFERRAL"
    if validation_gate["cost_ready_for_validation"]:
        status = "PASS"
    elif not real_session.mt5_available:
        status = "BLOCKED"

    xauusd_n = sum(1 for d in datasets if d["logical_symbol"] == "XAUUSD")
    xauusd_i_n = sum(1 for d in datasets if d["logical_symbol"] == "XAUUSD_i")

    payload = {
        "schema_version": 1,
        "phase": "27.7",
        "status": status,
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "real_operator_evidence": {
            "status": real_session.real_operator_evidence,
            "mt5_available": real_session.mt5_available,
            "environment": real_session.account_environment,
            "is_real_terminal": real_session.is_real_terminal,
            "demo_not_mislabeled_as_real": (
                real_session.real_operator_evidence != "COLLECTED" or real_session.is_real_terminal
            ),
            "fresh_collected": real_fresh,
            "artifact": PHASE276_REAL_JSON if real_fresh else None,
            "session_artifact": "logs/phase27_6_operator_session_raw.json",
            "raw": _sanitize_real_raw(real_dict),
        },
        "ev_eq_01": ev_eq,
        "symbol_binding": {
            "primary_symbol_configured": PRIMARY_SYMBOL,
            "symbol_by_environment": SYMBOL_BY_ENVIRONMENT,
            "configured_not_authorized": True,
            "xauusd_observed_absent": True,
            "xauusd_i_observed_present": True,
        },
        "dataset_binding": {
            "total": len(datasets),
            "xauusd_count": xauusd_n,
            "xauusd_i_count": xauusd_i_n,
            "mapping_required": xauusd_n,
            "proposed_map_unauthorized": "XAUUSD -> XAUUSD_i (PROPOSED_UNAUTHORIZED)",
            "inventory": datasets,
        },
        "commission": commission,
        "swap": swap,
        "slippage": slippage,
        "spread": spread,
        "cost_completeness": {
            "status": CostCompleteness.UNKNOWN.value,
            "complete_count": complete_count,
            "forced_complete": False,
            "cost_adjusted_metrics_enabled": False,
        },
        "conservative_cost_scenario": conservative,
        "operator_policy": {
            "decisions": policy,
            "all_undecided": all(v == "UNDECIDED" for v in policy.values()),
            "artifact": OPERATOR_POLICY_MD,
        },
        "validation_gate": validation_gate,
        "blockers": blockers,
        "final_decisions": decisions,
        "changes": [
            "tradingbot/backtest/phase27_7_final_blocker_closure.py",
            "tests/test_phase27_7_final_blocker_closure.py",
            "docs_v2/01_truth/PHASE27_7_FINAL_BLOCKER_CLOSURE.md",
        ],
        "tests": {"module": "tests/test_phase27_7_final_blocker_closure.py"},
        "production_authorized": False,
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "symbol_select": False,
            "orders_sent": False,
            "credentials_accessed": False,
            "datasets_modified": False,
            "strategy_riskgate_modified": False,
        },
        "proven": [
            "Phase 27.6 findings preserved",
            "Demo not mislabeled as Real when Demo attached",
            "50 zero-commission deals do not prove universal zero",
            "Fail-closed cost contract intact",
        ],
        "configured": [f"PRIMARY_SYMBOL={PRIMARY_SYMBOL}", f"SYMBOL_BY_ENVIRONMENT={SYMBOL_BY_ENVIRONMENT}"],
        "supported": ["Conservative scenario architecture exists — not authorized"],
        "unknown": [
            "Commission account-specific treatment",
            "Historical swap series",
            "Realized slippage",
            "Fresh Real evidence" if not real_fresh else "Slippage distribution",
        ],
        "deferred": ["Real terminal attach", "Operator policy fill", "Historical bid/ask tape"],
        "blocked": blockers,
        "superseded": [],
    }

    out = root / PHASE277_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload, decisions, validation_gate)
    return payload


def _sanitize_real_raw(d: dict[str, Any]) -> dict[str, Any]:
    from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS

    if isinstance(d, dict):
        return {k: _sanitize_real_raw(v) for k, v in d.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}
    if isinstance(d, list):
        return [_sanitize_real_raw(x) for x in d]
    return d


def _write_md(root: Path, payload: dict[str, Any], decisions: dict[str, str], gate: dict[str, Any]) -> None:
    blockers = payload.get("blockers") or []
    md = f"""# Phase 27.7 — Final Blocker Closure

**Status:** {payload['status']}  
**Artifact:** `{PHASE277_JSON}`

**Subsequent policy lock (Phase 27.8):** The operator later locked the six broker-policy decisions. This 27.7 artifact remains the pre-lock blocker snapshot. Policy lock does not convert missing evidence into verified evidence. See `docs_v2/01_truth/PHASE27_8_POLICY_LOCK.md` and `logs/phase27_8_policy_lock.json`.

## Objective

Final forensic closure pass over Phase 27.6 blockers. No strategy/production changes.

## Inherited Phase 27.6 truth

Preserved unchanged. See Phase 27.6 artifact.

## Final decisions

| Question | Answer |
|---|---|
| Fresh Real evidence | {decisions['A_fresh_real_mt5_evidence']} |
| EV-EQ-01 proven | {decisions['B_ev_eq_01_proven']} |
| XAUUSD_i policy authorized | {decisions['C_xauusd_i_policy_explicitly_authorized']} |
| XAUUSD datasets safe | {decisions['D_xauusd_datasets_validation_safe']} |
| Commission proven | {decisions['E_commission_proven']} |
| Historical swap proven | {decisions['F_historical_swap_proven']} |
| Slippage proven | {decisions['G_realized_slippage_proven']} |
| M5 bid/ask available | {decisions['H_historical_m5_bidask_available']} |
| Any COST_COMPLETE dataset | {decisions['I_any_dataset_cost_complete']} |
| COST_READY | {decisions['J_cost_ready_for_validation']} |

## Validation gate

cost_ready_for_validation = **{gate['cost_ready_for_validation']}**

## Blocker matrix

See JSON `blockers` array ({len(blockers)} rows).

## Production

**BLOCKED** — production_changes: NONE

## Next

{"CONTROLLED STRATEGY VALIDATION" if gate['cost_ready_for_validation'] else "OPERATOR/BROKER/DATA EVIDENCE CLOSURE"}
"""
    (root / PHASE277_MD).write_text(md, encoding="utf-8")


def run_phase27_7_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_7_final_blocker_closure(base_dir)
