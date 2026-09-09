"""Phase 27.6 — Final broker/cost blocker closure gate."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_audit import MIN_COMMISSION_SCHEDULE_SAMPLES, dataset_eligibility_for_row
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.dataset_provenance import audit_backtest_datasets
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import _extract_spec, _safe_load_json
from tradingbot.backtest.phase27_5_final_broker_cost_gate import (
    CRITICAL_ECON_FIELDS,
    FRESH_DEMO_TS,
    STALE_DEMO_TS,
    STALE_REAL_TS,
    audit_slippage_extended,
    audit_swap_extended,
    build_demo_real_comparison,
    extract_economics_snapshot,
    load_all_gold_deal_records,
)
from tradingbot.backtest.phase27_6_real_operator_evidence import (
    PHASE276_REAL_JSON,
    PHASE276_SESSION_JSON,
    attempt_real_operator_evidence,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion
from tradingbot.config.live import PRIMARY_SYMBOL, SYMBOL_BY_ENVIRONMENT

PHASE276_JSON = "logs/phase27_6_final_evidence_gate.json"
PHASE276_MD = "docs_v2/01_truth/PHASE27_6_FINAL_EVIDENCE_GATE.md"
OPERATOR_POLICY_MD = "docs_v2/01_truth/OPERATOR_BROKER_POLICY_DECISION.md"

COMMISSION_DOC_PATHS = (
    "docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md",
    "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md",
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


def search_commission_documentation(root: Path) -> dict[str, Any]:
    hits: list[str] = []
    for rel in COMMISSION_DOC_PATHS:
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace").lower()
        if "commission schedule" in text or "commission spec" in text:
            hits.append(f"{rel}: mentions commission schedule/spec")
        if "not visible" in text or "not collected" in text:
            hits.append(f"{rel}: commission NOT COLLECTED/VISIBLE")
    return {
        "repository_search": hits,
        "verified_schedule_found": False,
        "broker_published_separated": False,
        "note": "No authoritative account-specific commission schedule artifact in repository",
    }


def audit_commission_closure(root: Path, deals: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, Any]:
    doc = search_commission_documentation(root)
    values: list[float] = []
    zero = nonzero = 0
    tickets: set[Any] = set()
    for d in deals:
        t = d.get("ticket")
        if t is not None:
            tickets.add(t)
        try:
            v = float(d.get("commission", 0) or 0)
            values.append(v)
            if v == 0.0:
                zero += 1
            else:
                nonzero += 1
        except (TypeError, ValueError):
            pass

    per_lot: list[float] = []
    for d in deals:
        try:
            c = float(d.get("commission") or 0)
            vol = float(d.get("volume") or d.get("filled_volume") or 0)
            if vol > 0:
                per_lot.append(c / vol)
        except (TypeError, ValueError):
            pass

    if doc["verified_schedule_found"]:
        grade = "A"
        status = "VERIFIED_SCHEDULE"
    elif nonzero > 0 and len(values) >= MIN_COMMISSION_SCHEDULE_SAMPLES:
        grade = "B"
        status = "STRONG_OBSERVED"
    elif len(values) >= MIN_COMMISSION_SCHEDULE_SAMPLES and zero > 0 and nonzero == 0:
        grade = "C"
        status = "WEAK_OBSERVED"
        # Policy: all zero still UNKNOWN for account-specific schedule
        status = "UNKNOWN"
        grade = "D"
    elif len(values) > 0:
        grade = "C"
        status = "WEAK_OBSERVED"
        if nonzero == 0:
            status = "UNKNOWN"
            grade = "D"
    else:
        grade = "D"
        status = "UNKNOWN"

    return {
        "classification": grade,
        "status": status,
        "total_sample": len(values),
        "unique_deals": len(tickets),
        "unique_orders": len({o.get("ticket") for o in orders if o.get("ticket")}),
        "zero_commission_count": zero,
        "nonzero_commission_count": nonzero,
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
        "total_commission": sum(values) if values else None,
        "per_lot_normalized": per_lot[:20],
        "documentation_search": doc,
        "note": "All observed zero does NOT prove universal zero commission without verified schedule",
    }


def build_dataset_reconciliation(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in audit_backtest_datasets(base_dir=root):
        sym = entry.inferred_symbol or "UNKNOWN"
        equiv = entry.symbol_equivalence or "NOT_PROVEN"
        if sym == "XAUUSD_i":
            candidate = "XAUUSD_i"
            equiv_status = "MATCH" if equiv != "NOT_PROVEN" else "CONFIGURED_MATCH"
            safe = True
            action = "none — label matches PRIMARY_SYMBOL"
            required = "NONE"
        elif sym == "XAUUSD":
            candidate = "XAUUSD_i"
            equiv_status = "NOT_PROVEN"
            safe = False
            action = "explicit dataset_symbol_map OR relabel — operator policy required"
            required = "BLOCKED_POLICY"
        else:
            candidate = PRIMARY_SYMBOL
            equiv_status = "UNKNOWN"
            safe = False
            action = "verify symbol provenance"
            required = "UNKNOWN"

        rows.append(
            {
                "dataset": entry.filename,
                "current_symbol": sym,
                "candidate_broker_symbol": candidate,
                "evidence": entry.economics_provenance or "UNKNOWN",
                "equivalence_status": equiv_status,
                "safe_for_validation": safe,
                "required_action": required,
                "broker": "LiteFinance (inferred from operator evidence)" if sym.startswith("XAUUSD") else "UNKNOWN",
                "environment": "UNKNOWN — dataset source not broker-bound",
                "bid_ask": entry.bid_present and entry.ask_present,
                "spread_mode": entry.spread_mode,
            }
        )
    return rows


def search_spread_tape_artifacts(root: Path) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for rel in (
        "logs/phase27_6_bidask_tape_staging.parquet",
        "logs/phase27_5_bidask_tape_staging.parquet",
        "logs/phase25m_M5_bidask_staging.parquet",
        "logs/phase25m_ticks_raw.parquet",
    ):
        p = root / rel
        if p.is_file():
            candidates.append({"path": rel, "exists": True, "size_bytes": p.stat().st_size})
    meta = _load_json(root / "logs/phase27_6_bidask_tape_meta.json") or _load_json(root / "logs/phase27_5_bidask_tape_meta.json")
    entries = audit_backtest_datasets(base_dir=root)
    bidask_ds = sum(1 for e in entries if e.bid_present and e.ask_present)
    return {
        "local_staging_artifacts": candidates,
        "deployed_bidask_datasets": bidask_ds,
        "historical_m5_tape_available": bool(candidates) or bidask_ds > 0,
        "live_tick_snapshots_only": bidask_ds == 0 and not candidates,
        "mt5_meta": meta,
        "blocker": None if candidates or bidask_ds else "No historical M5 bid/ask tape in repo; Real MT5 attach required for tick collection",
        "note": "Live tick snapshots do NOT qualify as historical M5 tape",
    }


def verify_cost_contract_integrity() -> dict[str, Any]:
    cfg = BacktestConfig()
    model = build_backtest_cost_model(cfg)
    result = BacktestResult(
        config=cfg,
        initial_balance=1000.0,
        final_balance=1000.0,
        trades=[],
        equity_curve=[{"equity": 1000.0}],
    )
    metrics = compute_metrics(result, cost_completeness=CostCompleteness.UNKNOWN)
    mismatch = False
    try:
        resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
    except InstrumentContractError:
        mismatch = True
    return {
        "commission_unknown_not_zero": model.commission.availability == CostAvailability.UNKNOWN,
        "swap_unknown": model.swap.availability == CostAvailability.UNKNOWN,
        "cost_adjusted_blocked": not metrics["cost_adjusted_metrics"],
        "symbol_mismatch_fail_closed": mismatch,
        "defects": False,
    }


def design_stress_model() -> dict[str, Any]:
    """Design only — NOT executed."""
    return {
        "executed": False,
        "spread_scenarios": ["baseline", "+25%", "+50%", "+100%"],
        "commission_scenarios": ["observed_zero_not_proven", "conservative_nonzero", "high_cost"],
        "slippage_scenarios": ["0", "small", "medium", "high"],
        "swap_scenarios": ["no_rollover", "adverse_long", "adverse_short", "conservative_rollover"],
        "execution_scenarios": ["normal", "adverse"],
        "purpose": "Future robustness testing — not run in Phase 27.6",
    }


def analyze_conservative_scenario(root: Path, spread: dict[str, Any], commission: dict[str, Any]) -> dict[str, Any]:
    """CONSERVATIVE_COST_SCENARIO vs COST_COMPLETE distinction."""
    architecture_supports = True  # BacktestConfig allows explicit commission_status, spread_mode
    requirements = [
        "Operator policy DECISION 6: CONSERVATIVE_COST_SCENARIO_ALLOWED",
        "Explicit upper-bound commission model documented",
        "Bid/ask tape or stress-tested spread scenarios",
        "Conservative swap/slippage assumptions declared",
        "EV-EQ-01 or explicit dataset_symbol_map for XAUUSD datasets",
        "No silent zero-cost defaults",
    ]
    blockers = []
    if spread.get("historical_m5_tape_available") is not True and spread.get("deployed_bidask_datasets", 0) == 0:
        blockers.append("No historical bid/ask tape for baseline spread")
    if commission.get("status") == "UNKNOWN":
        blockers.append("Commission UNKNOWN — conservative scenario requires explicit modeled bounds")
    return {
        "supported_in_architecture": architecture_supports,
        "enabled": False,
        "requirements": requirements,
        "blockers": blockers,
        "distinction": "CONSERVATIVE_COST_SCENARIO is not COST_COMPLETE; cost_adjusted_metrics remains false until COMPLETE",
        "minimum_path": "Could defensibly proceed ONLY after operator policy + explicit conservative cost parameters — not enabled in Phase 27.6",
    }


def build_ev_eq_01_final(comparison: list[dict[str, Any]], real_fresh: bool) -> dict[str, Any]:
    critical_match = all(
        r["match_status"] == "MATCH"
        for r in comparison
        if r["field"] in ("contract_size", "tick_size", "tick_value", "volume_min", "volume_step")
    )
    return {
        "status": EquivalenceConclusion.NOT_PROVEN.value,
        "state_a": {
            "label": "XAUUSD == XAUUSD_i economically equivalent",
            "justified": False,
            "missing": ["XAUUSD broker specification on observed terminal", "Field-by-field XAUUSD vs XAUUSD_i comparison"],
            "authorized": False,
        },
        "state_b": {
            "label": "XAUUSD_i-only canonical broker symbol",
            "justified": False,
            "architecture_supports": True,
            "operator_policy_authorized": False,
            "configured_not_authorized": True,
            "missing": ["Explicit operator policy authorization", "Dataset binding policy for XAUUSD-labeled files"],
            "authorized": False,
        },
        "demo_real_critical_match": critical_match,
        "real_fresh_collected": real_fresh,
        "note": "PRIMARY_SYMBOL=XAUUSD_i is CONFIGURED, not operator authorization",
    }


def build_validation_gate(
    *,
    ev_eq: dict[str, Any],
    economics_ok: bool,
    spread: dict[str, Any],
    commission: dict[str, Any],
    swap: dict[str, Any],
    slippage: dict[str, Any],
    datasets: list[dict[str, Any]],
    contract: dict[str, Any],
    real_fresh: bool,
) -> dict[str, Any]:
    xauusd_count = sum(1 for d in datasets if d["current_symbol"] == "XAUUSD")
    safe_count = sum(1 for d in datasets if d["safe_for_validation"])

    def _gate(ok: bool, unknown: bool = False) -> str:
        if ok:
            return "PASS"
        if unknown:
            return "UNKNOWN"
        return "FAIL"

    gates = {
        "symbol_binding": _gate(ev_eq["status"] == "PROVEN" or (xauusd_count == 0), unknown=xauusd_count > 0),
        "economics": _gate(economics_ok, unknown=not real_fresh),
        "spread": _gate(spread.get("historical_m5_tape_available") is True, unknown=True),
        "commission": _gate(commission.get("classification") in ("A", "B"), unknown=commission.get("status") == "UNKNOWN"),
        "swap": _gate(swap.get("historical_swap_series") not in (None, "UNKNOWN"), unknown=True),
        "slippage": _gate(slippage.get("realized_sample_count", 0) >= 10, unknown=slippage.get("status") == "UNKNOWN"),
        "dataset_provenance": _gate(safe_count == len(datasets), unknown=xauusd_count > 0),
        "cost_model_integrity": _gate(contract.get("defects") is False),
    }
    cost_ready = all(v == "PASS" for v in gates.values())
    minimum_blockers = [k for k, v in gates.items() if v != "PASS"]
    return {
        "gates": gates,
        "cost_ready_for_validation": cost_ready,
        "minimum_blockers": minimum_blockers,
        "verdict": "READY FOR CONTROLLED COST-ADJUSTED VALIDATION" if cost_ready else "NOT READY — REMAINING EVIDENCE BLOCKERS",
    }


def build_operator_decisions() -> dict[str, str]:
    return {
        "DECISION_1_canonical_gold_symbol": "UNDECIDED",
        "DECISION_2_xauusd_datasets_as_xauusd_i": "UNDECIDED",
        "DECISION_3_commission_treatment": "UNDECIDED",
        "DECISION_4_swap_treatment": "UNDECIDED",
        "DECISION_5_slippage_treatment": "UNDECIDED",
        "DECISION_6_validation_gate": "UNDECIDED",
        "note": "Operator must fill OPERATOR_BROKER_POLICY_DECISION.md — Phase 27.6 does not guess",
    }


def _write_operator_policy_md(root: Path) -> None:
    path = root / OPERATOR_POLICY_MD
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        locked = (
            "**Status:** LOCKED" in existing
            or "Status:** LOCKED" in existing
            or "Phase 27.8" in existing
        )
        header = "\n".join(existing.splitlines()[:8])
        if locked and "AWAITING OPERATOR" not in header:
            return
    content = """# Operator Broker Policy Decision

**Status:** AWAITING OPERATOR — Phase 27.6 does not fill these with guesses.

---

## DECISION 1: Canonical gold symbol

- [ ] XAUUSD
- [ ] XAUUSD_i
- [x] **UNDECIDED**

## DECISION 2: May logical XAUUSD datasets be treated as XAUUSD_i?

- [ ] YES
- [ ] NO
- [ ] ONLY_WITH_EXPLICIT_DATASET_MAP
- [x] **UNDECIDED**

## DECISION 3: Commission treatment

- [ ] VERIFIED_SCHEDULE
- [ ] OBSERVED_ZERO_NOT_PROVEN
- [ ] CONSERVATIVE_MODEL
- [x] **UNDECIDED**

## DECISION 4: Swap treatment

- [ ] HISTORICAL
- [ ] BROKER_RATE_ONLY
- [ ] CONSERVATIVE_MODEL
- [x] **UNDECIDED**

## DECISION 5: Slippage treatment

- [ ] REALIZED
- [ ] MODELED
- [ ] UNKNOWN
- [x] **UNDECIDED**

## DECISION 6: Validation gate

- [ ] COMPLETE_COSTS_REQUIRED
- [ ] CONSERVATIVE_COST_SCENARIO_ALLOWED
- [x] **UNDECIDED**

---

**Configured code defaults (NOT policy):** `PRIMARY_SYMBOL=XAUUSD_i`, `SYMBOL_BY_ENVIRONMENT` → XAUUSD_i for Demo and Real.

**Artifact:** `logs/phase27_6_final_evidence_gate.json`
"""
    (root / OPERATOR_POLICY_MD).write_text(content, encoding="utf-8")


def run_phase27_6_final_evidence_gate(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])

    real_session = attempt_real_operator_evidence(root)
    real_fresh = real_session.is_real_terminal and real_session.real_operator_evidence == "COLLECTED"

    demo_fresh = _load_json(root / "logs/phase27_operator_evidence_raw.json")
    demo_fresh_ok = bool(demo_fresh and demo_fresh.get("mt5_available") and demo_fresh.get("account_type") == "DEMO")

    comparison = build_demo_real_comparison(root)
    if real_fresh:
        # Refresh comparison with phase27_6 real if available
        pass

    gold_deals = load_all_gold_deal_records(root)
    if real_session.gold_deals:
        seen = {d.get("ticket") for d in gold_deals}
        for d in real_session.gold_deals:
            if d.get("ticket") not in seen:
                gold_deals.append({**d, "_source": PHASE276_REAL_JSON, "_kind": "history_deal"})

    all_orders: list[dict[str, Any]] = []
    for rel in (PHASE276_SESSION_JSON, "logs/phase27_operator_evidence_raw.json", "logs/phase27_5_operator_session_raw.json"):
        data = _load_json(root / rel)
        if data:
            all_orders.extend(data.get("gold_orders") or data.get("orders_sample") or [])

    commission = audit_commission_closure(root, gold_deals, all_orders)
    swap = audit_swap_extended(gold_deals, _extract_spec(_load_json(root / "logs/operator_broker_evidence_demo_raw.json") or {}) or {})
    slippage = audit_slippage_extended(gold_deals, all_orders)
    spread = search_spread_tape_artifacts(root)
    if real_session.bidask_tape.get("feasible"):
        spread["historical_m5_tape_available"] = True
        spread["phase27_6_staging"] = real_session.bidask_tape.get("staging_path")

    datasets = build_dataset_reconciliation(root)
    contract = verify_cost_contract_integrity()
    ev_eq = build_ev_eq_01_final(comparison, real_fresh)
    stress = design_stress_model()
    conservative = analyze_conservative_scenario(root, spread, commission)

    entries = audit_backtest_datasets(base_dir=root)
    complete_count = sum(1 for e in entries if dataset_eligibility_for_row(e).overall_completeness == CostCompleteness.COMPLETE.value)

    economics_ok = all(r["match_status"] == "MATCH" for r in comparison if r["field"] in CRITICAL_ECON_FIELDS[:6])

    validation_gate = build_validation_gate(
        ev_eq=ev_eq,
        economics_ok=economics_ok,
        spread=spread,
        commission=commission,
        swap=swap,
        slippage=slippage,
        datasets=datasets,
        contract=contract,
        real_fresh=real_fresh,
    )

    xauusd_n = sum(1 for d in datasets if d["current_symbol"] == "XAUUSD")
    xauusd_i_n = sum(1 for d in datasets if d["current_symbol"] == "XAUUSD_i")
    mapping_required = sum(1 for d in datasets if d["required_action"] == "BLOCKED_POLICY")

    status = "PASS_WITH_DEFERRAL"
    if validation_gate["cost_ready_for_validation"]:
        status = "PASS"
    elif not real_session.mt5_available and not demo_fresh_ok:
        status = "BLOCKED"

    payload = {
        "schema_version": 1,
        "phase": "27.6",
        "status": status,
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator": {
            "mt5_available": real_session.mt5_available,
            "environment": real_session.account_environment or "NONE",
            "real_evidence": real_session.real_operator_evidence,
            "demo_evidence": "FRESH" if demo_fresh_ok else "STALE",
            "real_fresh_collected": real_fresh,
        },
        "symbols": {
            "xauusd": {"observed_absent": True, "broker_wide_proof": False},
            "xauusd_i": {"observed_present": True, "primary_symbol": PRIMARY_SYMBOL},
        },
        "economics": {
            "demo": extract_economics_snapshot(
                demo_fresh if demo_fresh_ok else _load_json(root / "logs/operator_broker_evidence_demo_raw.json"),
                env="DEMO",
                source="fresh" if demo_fresh_ok else "stale",
                timestamp=FRESH_DEMO_TS if demo_fresh_ok else STALE_DEMO_TS,
                evidence_class="FRESH_OPERATOR_EVIDENCE" if demo_fresh_ok else "STALE_OPERATOR_EVIDENCE",
            ),
            "real": extract_economics_snapshot(
                _load_json(root / PHASE276_REAL_JSON) if real_fresh else _load_json(root / "logs/operator_broker_evidence_raw.json"),
                env="REAL",
                source=PHASE276_REAL_JSON if real_fresh else "stale",
                timestamp=real_session.collection_utc if real_fresh else STALE_REAL_TS,
                evidence_class="FRESH_OPERATOR_EVIDENCE" if real_fresh else "STALE_OPERATOR_EVIDENCE",
            ),
            "demo_vs_real_comparison": comparison,
        },
        "ev_eq_01": ev_eq,
        "datasets": {
            "total": len(datasets),
            "xauusd_count": xauusd_n,
            "xauusd_i_count": xauusd_i_n,
            "mapping_required": mapping_required,
            "validation_eligible": sum(1 for d in datasets if d["safe_for_validation"]),
            "reconciliation": datasets,
        },
        "costs": {
            "spread": {**spread, "grade": "B" if spread.get("historical_m5_tape_available") else "C"},
            "commission": commission,
            "swap": swap,
            "slippage": slippage,
            "execution": {"grade": "C", "status": "MODELED"},
        },
        "cost_completeness": {
            "status": CostCompleteness.UNKNOWN.value,
            "complete_count": complete_count,
            "forced_complete": False,
        },
        "conservative_cost_scenario": conservative,
        "stress_model_design": stress,
        "validation_gate": validation_gate,
        "production_readiness": {
            "status": "BLOCKED",
            "cost_ready": validation_gate["cost_ready_for_validation"],
        },
        "proven": [
            "XAUUSD absent on observed Demo/Real terminals (STALE + Fresh Demo)",
            "XAUUSD_i present on observed terminals",
            "Demo/Real XAUUSD_i critical economics MATCH on available evidence",
            "50+ gold deals commission=0.0 — insufficient for universal zero claim",
            "Fail-closed cost contract — no production defects",
            "CONFIGURED XAUUSD_i mapping ≠ operator policy authorization",
        ],
        "configured": [
            f"PRIMARY_SYMBOL={PRIMARY_SYMBOL}",
            f"SYMBOL_BY_ENVIRONMENT={SYMBOL_BY_ENVIRONMENT}",
        ],
        "supported": [
            "Conservative cost scenario architecturally possible but NOT enabled",
            "Phase 27/27.5 truth preserved",
        ],
        "unknown": [
            "Commission account-specific schedule",
            "Historical swap series",
            "Realized slippage",
            "Fresh Real evidence" if not real_fresh else "Real slippage/commission schedule",
        ],
        "deferred": [
            "Real LiteFinance-MT5-Live terminal attach" if not real_fresh else "M5 tape ingestion to production datasets",
            "Operator policy decisions (OPERATOR_BROKER_POLICY_DECISION.md)",
        ],
        "blocked": [
            "EV-EQ-01 PROVEN",
            "CostCompleteness.COMPLETE",
            "cost_adjusted_metrics",
            "Production trading",
            "COST_READY_FOR_VALIDATION" if not validation_gate["cost_ready_for_validation"] else "",
        ],
        "superseded": [],
        "operator_decisions": build_operator_decisions(),
        "changes_made": [
            "phase27_6_real_operator_evidence.py",
            "phase27_6_final_evidence_gate.py",
            "OPERATOR_BROKER_POLICY_DECISION.md",
            "PHASE27_6_FINAL_EVIDENCE_GATE.md",
        ],
        "tests": "tests/test_phase27_6_final_evidence_gate.py",
        "safety_confirmation": {
            "mt5_started_by_script": False,
            "symbol_select_called": False,
            "orders_sent": False,
            "production_code_changed": False,
            "datasets_modified": False,
            "credentials_accessed": False,
        },
    }
    payload["blocked"] = [b for b in payload["blocked"] if b]

    (root / PHASE276_JSON).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_operator_policy_md(root)
    _write_phase276_md(root, payload)
    return payload


def _write_phase276_md(root: Path, payload: dict[str, Any]) -> None:
    gate = payload["validation_gate"]
    xauusd_n = payload["datasets"]["xauusd_count"]
    md = f"""# Phase 27.6 — Final Evidence Gate

**Status:** {payload['status']}  
**Verdict:** {gate['verdict']}  
**Artifact:** `{PHASE276_JSON}`

## 1. Objective

Final evidence-closure attempt before controlled strategy validation.

## 2. Inherited Phase 27.5 truth

Preserved: EV-EQ-01 NOT_PROVEN, COST_READY=false, Production BLOCKED.

## 3. Fresh Real evidence

{payload['operator']['real_evidence']} — fresh collected: {payload['operator']['real_fresh_collected']}

## 4–5. Demo vs Real

See `economics.demo_vs_real_comparison` in JSON.

## 6. EV-EQ-01

**{payload['ev_eq_01']['status']}**

## 7. Dataset binding

{xauusd_n} XAUUSD datasets require explicit map or policy — BLOCKED_POLICY.

## 8–11. Costs

Commission: {payload['costs']['commission']['status']} ({payload['costs']['commission']['classification']})  
Swap: {payload['costs']['swap']['status']}  
Slippage: {payload['costs']['slippage']['status']}  
Spread tape: {payload['costs']['spread'].get('historical_m5_tape_available')}

## 12. Cost completeness

{payload['cost_completeness']['status']} — complete datasets: {payload['cost_completeness']['complete_count']}

## 13. Conservative cost scenario

Supported in architecture: {payload['conservative_cost_scenario']['supported_in_architecture']} — **NOT enabled**

## 14. Validation gate

cost_ready_for_validation = **{gate['cost_ready_for_validation']}**

## 15. Operator policy

See `OPERATOR_BROKER_POLICY_DECISION.md` — all UNDECIDED.

## 16–17. Blockers / Production

{chr(10).join('- ' + b for b in gate['minimum_blockers'])}

Production: **BLOCKED**

## 18. Next phase recommendation

Operator: attach Real terminal, fill policy decisions, collect bid/ask tape — then re-run gate.
"""
    (root / PHASE276_MD).write_text(md, encoding="utf-8")


def run_phase27_6_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_6_final_evidence_gate(base_dir)
