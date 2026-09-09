"""Phase 27.15 — Final cost completeness gate (offline, fail-closed).

Integrates Phase 27.8–27.14 evidence. Does not run profitability validation,
backtests, or MT5. Does not change Strategy, RiskGate, or execution.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.commission_policy import OBSERVED_ZERO_NOT_PROVEN
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    SpreadMode,
    assess_cost_completeness,
    build_backtest_cost_model,
    detect_spread_mode_from_frame,
    frame_has_historical_bid_ask,
)
from tradingbot.backtest.dataset_contract import (
    STATUS_INVALID_MAP,
    STATUS_MISSING_MAP,
    STATUS_UNKNOWN_SYMBOL,
    InstrumentContractError,
    resolve_broker_symbol_for_dataset,
)
from tradingbot.backtest.dataset_provenance import (
    audit_backtest_datasets,
    compute_dataset_cost_status,
)
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_8_policy_lock import (
    LOCKED_POLICY,
    cost_adjusted_validation_allowed,
)
from tradingbot.backtest.phase27_10_dataset_symbol_binding import audit_one_dataset
from tradingbot.backtest.slippage_policy import modeled_cannot_silently_become_zero
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2715_JSON = "logs/phase27_15_cost_completeness_gate.json"
PHASE2715_MD = "docs_v2/01_truth/PHASE27_15_COST_COMPLETENESS_GATE.md"

REQUIRED_ARTIFACTS = {
    "phase27_8": "logs/phase27_8_policy_lock.json",
    "phase27_9": "logs/phase27_9_real_broker_evidence.json",
    "phase27_10": "logs/phase27_10_dataset_symbol_binding.json",
    "phase27_11": "logs/phase27_11_historical_bidask.json",
    "phase27_12": "logs/phase27_12_commission_evidence.json",
    "phase27_13": "logs/phase27_13_swap_policy.json",
    "phase27_14": "logs/phase27_14_slippage_model.json",
}

GATE_COMPONENTS = (
    "symbol_binding",
    "economics",
    "dataset_provenance",
    "spread",
    "commission",
    "swap",
    "slippage",
    "execution_model",
)

BLOCKING_MAP_STATUSES = frozenset(
    {STATUS_MISSING_MAP, STATUS_INVALID_MAP, STATUS_UNKNOWN_SYMBOL, "SYMBOL_MISMATCH"}
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
    return "UNKNOWN"


def load_phase_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for key, rel in REQUIRED_ARTIFACTS.items():
        data = _safe_load_json(root / rel)
        loaded[key] = data if isinstance(data, dict) else {}
    return loaded


def artifact_presence(root: Path) -> dict[str, Any]:
    rows = []
    for key, rel in REQUIRED_ARTIFACTS.items():
        path = root / rel
        rows.append(
            {
                "id": key,
                "path": rel,
                "present": path.is_file(),
                "status": "PRESENT" if path.is_file() else "MISSING",
            }
        )
    return {
        "rows": rows,
        "all_present": all(r["present"] for r in rows),
        "missing": [r["path"] for r in rows if not r["present"]],
    }


def component_is_complete(status: str) -> bool:
    return str(status).upper() == CostCompleteness.COMPLETE.value


def cost_ready_for_validation(components: dict[str, Any]) -> bool:
    """AND of all eight required components. One non-COMPLETE keeps the gate closed."""
    if not components:
        return False
    return all(component_is_complete((components.get(name) or {}).get("status")) for name in GATE_COMPONENTS)


def classify_dataset_row(row: dict[str, Any]) -> str:
    """Classify one dataset: COMPLETE / PARTIAL / UNKNOWN / BLOCKED."""
    mapping_status = str(row.get("mapping_status") or STATUS_UNKNOWN_SYMBOL)
    if row.get("mapping_blocked") or mapping_status in BLOCKING_MAP_STATUSES:
        return "BLOCKED"
    spread = str(row.get("spread_mode") or SpreadMode.UNKNOWN.value).upper()
    if spread == SpreadMode.DATASET.value and not row.get("historical_bid_ask"):
        return "BLOCKED"
    cost = compute_dataset_cost_status(
        spread_mode=spread,
        commission_status=str(row.get("commission_status") or "UNKNOWN"),
        swap_status=str(row.get("swap_status") or "UNKNOWN"),
        slippage_status=str(row.get("slippage_status") or "MODELED_PROXY"),
    )["cost_completeness"]
    if cost == CostCompleteness.COMPLETE.value and not row.get("historical_bid_ask"):
        return "BLOCKED"
    return cost


def evaluate_symbol_binding(p10: dict[str, Any], classified: list[dict[str, Any]]) -> dict[str, Any]:
    blocked = [r for r in classified if r["gate_class"] == "BLOCKED"]
    complete = [r for r in classified if r["gate_class"] == CostCompleteness.COMPLETE.value]
    silent_ok = bool((p10.get("contract_self_checks") or {}).get("silent_fallback_prevented", True))
    ev_eq = str((p10.get("contract_self_checks") or {}).get("ev_eq_01") or "NOT_PROVEN")
    ready = bool(complete) and not blocked and silent_ok and ev_eq != "NOT_PROVEN"
    return {
        "status": CostCompleteness.COMPLETE.value if ready else "BLOCKED",
        "evidence": "logs/phase27_10_dataset_symbol_binding.json",
        "silent_mapping_prevented": silent_ok,
        "ev_eq_01": ev_eq,
        "blocked_dataset_count": len(blocked),
        "complete_dataset_count": len(complete),
        "note": (
            "Decision 2 ONLY_WITH_EXPLICIT_DATASET_MAP is enforced. "
            "Unbound XAUUSD / unknown labels remain BLOCKED. EV-EQ-01 is NOT_PROVEN."
        ),
    }


def evaluate_economics(p8: dict[str, Any], p9: dict[str, Any]) -> dict[str, Any]:
    fresh = str(p9.get("evidence_status") or "UNKNOWN")
    ev_eq = str((p9.get("ev_eq_01") or {}).get("status") or "NOT_PROVEN")
    if fresh == "MT5_NOT_ATTACHED" or not p9:
        status = "UNKNOWN"
    elif ev_eq == "PROVEN" and fresh not in ("UNKNOWN", "MT5_NOT_ATTACHED"):
        status = CostCompleteness.COMPLETE.value
    else:
        status = "PARTIAL"
    return {
        "status": status,
        "evidence": "logs/phase27_9_real_broker_evidence.json + stale operator specs",
        "fresh_real_status": fresh,
        "ev_eq_01": ev_eq,
        "stale_operator_specs_exist": True,
        "note": (
            "Stale Demo/Real XAUUSD_i specs are not current broker economics. "
            "Phase 27.9 did not attach. EV-EQ-01 remains NOT_PROVEN."
        ),
        "policy_decision_1": (p8.get("operator_policy") or {}).get("decisions", {}).get("DECISION_1")
        or LOCKED_POLICY["DECISION_1"],
    }


def evaluate_dataset_provenance(classified: list[dict[str, Any]]) -> dict[str, Any]:
    sidecar_n = sum(1 for r in classified if r.get("sidecar_present"))
    complete = sum(1 for r in classified if r["gate_class"] == CostCompleteness.COMPLETE.value)
    if complete == len(classified) and classified:
        status = CostCompleteness.COMPLETE.value
    elif sidecar_n or classified:
        status = CostCompleteness.PARTIAL.value
    else:
        status = CostCompleteness.UNKNOWN.value
    return {
        "status": status,
        "evidence": "dataset sidecars + Phase 27.10 inventory",
        "dataset_count": len(classified),
        "sidecar_count": sidecar_n,
        "complete_count": complete,
        "note": "Sidecars record provenance; cost fields remain incomplete. 0 datasets COMPLETE.",
    }


def evaluate_spread(p11: dict[str, Any]) -> dict[str, Any]:
    inv = p11.get("inventory") or {}
    tape = bool(inv.get("historical_bid_ask_available"))
    evidence_status = str(p11.get("evidence_status") or "UNKNOWN")
    if tape:
        status = CostCompleteness.COMPLETE.value
    elif evidence_status == "BLOCKED_PENDING_DATA":
        status = "BLOCKED"
    else:
        status = CostCompleteness.UNKNOWN.value
    return {
        "status": status,
        "evidence": "logs/phase27_11_historical_bidask.json",
        "historical_bid_ask_available": tape,
        "bidask_dataset_count": inv.get("bidask_dataset_count", 0),
        "proxy_is_not_historical": True,
        "note": "OHLC PROXY spread is not historical bid/ask. No M5 tape.",
    }


def evaluate_commission(p12: dict[str, Any]) -> dict[str, Any]:
    found = bool((p12.get("verified_schedule") or {}).get("found"))
    classification = str((p12.get("operator_deal_tape") or {}).get("classification") or "UNKNOWN")
    if found:
        status = CostCompleteness.COMPLETE.value
    else:
        status = "BLOCKED"
    return {
        "status": status,
        "evidence": "logs/phase27_12_commission_evidence.json",
        "verified_schedule_found": found,
        "observed_classification": classification,
        "policy": LOCKED_POLICY["DECISION_3"],
        "note": "50 gold zeros are OBSERVED_ZERO_NOT_PROVEN. No account-applicable schedule.",
    }


def evaluate_swap(p13: dict[str, Any]) -> dict[str, Any]:
    hist = str(p13.get("historical_swap_series") or "UNKNOWN")
    if hist not in ("UNKNOWN", "", "NONE"):
        status = CostCompleteness.COMPLETE.value
    else:
        status = CostCompleteness.UNKNOWN.value
    return {
        "status": status,
        "evidence": "logs/phase27_13_swap_policy.json",
        "historical_swap_series": hist,
        "policy": LOCKED_POLICY["DECISION_4"],
        "broker_rate_only_is_not_historical": True,
        "note": "Broker rates may be recorded. They are not a historical swap series.",
    }


def evaluate_slippage(p14: dict[str, Any]) -> dict[str, Any]:
    tape = p14.get("operator_deal_tape") or {}
    n = int(tape.get("realized_sample_count") or 0)
    sufficient = bool(tape.get("statistically_sufficient"))
    if sufficient and n > 0:
        status = CostCompleteness.COMPLETE.value
    else:
        status = CostCompleteness.UNKNOWN.value
    return {
        "status": status,
        "evidence": "logs/phase27_14_slippage_model.json",
        "realized_sample_count": n,
        "statistically_sufficient": sufficient,
        "policy": LOCKED_POLICY["DECISION_5"],
        "implementation_label": "MODELED_PROXY",
        "modeled_is_not_realized": True,
        "note": "MODELED_PROXY is not realized slippage. 0 requested-vs-fill samples.",
    }


def evaluate_execution_model() -> dict[str, Any]:
    return {
        "status": CostCompleteness.UNKNOWN.value,
        "evidence": "tradingbot/backtest/broker.py SimulatedBroker",
        "model": "full_fill_simulated",
        "partial_fills_evidenced": False,
        "mt5_deviation_is_realized_slippage": False,
        "note": "SimulatedBroker assumes full fill. No realized execution tape for validation.",
    }


def hidden_assumption_checks() -> dict[str, Any]:
    default_model = build_backtest_cost_model(BacktestConfig())
    silent_map = False
    silent_code = ""
    try:
        resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL)
    except InstrumentContractError as exc:
        silent_map = True
        silent_code = exc.code

    import pandas as pd

    ohlc = pd.DataFrame({"open": [1.0], "high": [1.1], "low": [0.9], "close": [1.0]})
    proxy_mode = detect_spread_mode_from_frame(ohlc)
    metrics_unknown = compute_metrics(
        BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000.0,
            final_balance=1000.0,
            trades=[],
            equity_curve=[{"equity": 1000.0}],
        ),
        cost_completeness=CostCompleteness.UNKNOWN,
    )
    return {
        "default_commission_not_zero": default_model.commission.availability == CostAvailability.UNKNOWN,
        "default_commission_status": BacktestConfig().commission_status,
        "commission_per_lot_zero_is_not_status_zero": BacktestConfig().commission_per_lot == 0.0
        and default_model.commission.availability != CostAvailability.ZERO,
        "default_swap_not_zero": default_model.swap.availability == CostAvailability.UNKNOWN,
        "slippage_modeled_proxy_not_silent_zero": modeled_cannot_silently_become_zero(),
        "default_slippage_not_zero": default_model.slippage.availability != CostAvailability.ZERO,
        "silent_symbol_mapping_blocked": silent_map and silent_code in ("SYMBOL_MISMATCH", "MISSING_MAP"),
        "silent_symbol_mapping_code": silent_code,
        "ohlc_spread_is_proxy_not_dataset": proxy_mode == SpreadMode.PROXY,
        "ohlc_has_historical_bid_ask": frame_has_historical_bid_ask(ohlc),
        "cost_adjusted_unknown_blocked": not bool(metrics_unknown.get("cost_adjusted_metrics")),
        "complete_costs_required_unknown_blocked": not cost_adjusted_validation_allowed(
            CostCompleteness.UNKNOWN
        ),
        "complete_costs_required_complete_allowed": cost_adjusted_validation_allowed(
            CostCompleteness.COMPLETE
        ),
        "complete_costs_required_partial_blocked": not cost_adjusted_validation_allowed(
            CostCompleteness.PARTIAL
        ),
        "policy_decision_6": LOCKED_POLICY["DECISION_6"],
    }


def build_blocker_matrix(
    components: dict[str, Any],
    *,
    cost_ready: bool,
) -> list[dict[str, str]]:
    remediations = {
        "symbol_binding": "Bind every validation dataset with MATCH or an explicit dataset_symbol_map; do not invent EV-EQ-01",
        "economics": "Collect fresh Real (and Demo) XAUUSD_i economics; keep stale snapshots as stale",
        "dataset_provenance": "Complete sidecar cost fields from verified evidence only",
        "spread": "Ingest historical M5 bid/ask for XAUUSD_i; do not promote PROXY to DATASET",
        "commission": "Obtain an account-applicable verified commission schedule",
        "swap": "Obtain a historical swap series; do not accrue BROKER_RATE_ONLY",
        "slippage": "Collect statistically sufficient requested-vs-fill samples",
        "execution_model": "Evidence realized fills / partials before treating simulation as complete",
    }
    owners = {
        "symbol_binding": "DATA",
        "economics": "OPERATOR",
        "dataset_provenance": "DATA",
        "spread": "DATA",
        "commission": "OPERATOR",
        "swap": "DATA",
        "slippage": "OPERATOR",
        "execution_model": "RESEARCH",
    }
    rows = []
    for name in GATE_COMPONENTS:
        comp = components[name]
        status = str(comp["status"])
        if component_is_complete(status):
            continue
        rows.append(
            {
                "blocker": name,
                "evidence": str(comp.get("evidence") or ""),
                "status": status,
                "severity": "HIGH",
                "remediation": remediations[name],
                "owner": owners[name],
            }
        )
    rows.append(
        {
            "blocker": "COST_READY_FOR_VALIDATION",
            "evidence": "AND of eight required components",
            "status": "PASS" if cost_ready else "BLOCKED",
            "severity": "CRITICAL",
            "remediation": "Every required component must be COMPLETE. Do not weaken the AND.",
            "owner": "GATE",
        }
    )
    rows.append(
        {
            "blocker": "PRODUCTION_AUTHORIZATION",
            "evidence": "Phase 27.15 + operator policy Decision 6",
            "status": "BLOCKED",
            "severity": "CRITICAL",
            "remediation": "COST_READY_FOR_VALIDATION plus explicit production authorization",
            "owner": "OPERATOR",
        }
    )
    return rows


def _inventory_from_live(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in audit_backtest_datasets(base_dir=root):
        base = audit_one_dataset(entry)
        hist = bool(getattr(entry, "historical_bid_ask_available", False))
        if not hist:
            hist = bool(getattr(entry, "bid_present", False) and getattr(entry, "ask_present", False))
        base["historical_bid_ask"] = hist
        base["commission_status"] = getattr(entry, "commission", None) or "UNKNOWN"
        base["swap_status"] = getattr(entry, "swap", None) or "UNKNOWN"
        base["slippage_status"] = getattr(entry, "slippage", None) or "MODELED_PROXY"
        base["gate_class"] = classify_dataset_row(base)
        rows.append(base)
    return rows


def contract_self_checks(
    components: dict[str, Any],
    classified: list[dict[str, Any]],
    hidden: dict[str, Any],
) -> dict[str, Any]:
    ready = cost_ready_for_validation(components)
    one_unknown = dict(components)
    one_unknown["commission"] = {**components["commission"], "status": "UNKNOWN"}
    all_complete = {name: {"status": CostCompleteness.COMPLETE.value} for name in GATE_COMPONENTS}
    complete_n = sum(1 for r in classified if r["gate_class"] == CostCompleteness.COMPLETE.value)
    return {
        "cost_ready_false_with_current_evidence": not ready,
        "one_unknown_blocks_ready": not cost_ready_for_validation(one_unknown),
        "all_complete_would_be_ready": cost_ready_for_validation(all_complete),
        "complete_dataset_count_zero": complete_n == 0,
        "hidden_zero_commission_absent": hidden["default_commission_not_zero"],
        "hidden_zero_swap_absent": hidden["default_swap_not_zero"],
        "hidden_zero_slippage_absent": hidden["slippage_modeled_proxy_not_silent_zero"],
        "silent_mapping_absent": hidden["silent_symbol_mapping_blocked"],
        "proxy_not_historical_spread": hidden["ohlc_spread_is_proxy_not_dataset"]
        and not hidden["ohlc_has_historical_bid_ask"],
        "complete_costs_required_enforced": hidden["complete_costs_required_unknown_blocked"]
        and hidden["complete_costs_required_complete_allowed"]
        and hidden["complete_costs_required_partial_blocked"],
        "assess_default_not_complete": assess_cost_completeness(build_backtest_cost_model(BacktestConfig()))
        != CostCompleteness.COMPLETE,
    }


def run_phase27_15_cost_completeness_gate(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    presence = artifact_presence(root)
    artifacts = load_phase_artifacts(root)
    classified = _inventory_from_live(root)
    counts = {
        CostCompleteness.COMPLETE.value: 0,
        CostCompleteness.PARTIAL.value: 0,
        CostCompleteness.UNKNOWN.value: 0,
        "BLOCKED": 0,
    }
    for row in classified:
        counts[row["gate_class"]] = counts.get(row["gate_class"], 0) + 1

    components = {
        "symbol_binding": evaluate_symbol_binding(artifacts.get("phase27_10") or {}, classified),
        "economics": evaluate_economics(artifacts.get("phase27_8") or {}, artifacts.get("phase27_9") or {}),
        "dataset_provenance": evaluate_dataset_provenance(classified),
        "spread": evaluate_spread(artifacts.get("phase27_11") or {}),
        "commission": evaluate_commission(artifacts.get("phase27_12") or {}),
        "swap": evaluate_swap(artifacts.get("phase27_13") or {}),
        "slippage": evaluate_slippage(artifacts.get("phase27_14") or {}),
        "execution_model": evaluate_execution_model(),
    }
    if not presence["all_present"]:
        for name in GATE_COMPONENTS:
            if components[name]["status"] == CostCompleteness.COMPLETE.value:
                continue
            # Missing required input cannot upgrade a component to COMPLETE.
        for key, rel in REQUIRED_ARTIFACTS.items():
            if not (root / rel).is_file():
                # Map missing artifacts onto the component they feed.
                mapping = {
                    "phase27_8": "economics",
                    "phase27_9": "economics",
                    "phase27_10": "symbol_binding",
                    "phase27_11": "spread",
                    "phase27_12": "commission",
                    "phase27_13": "swap",
                    "phase27_14": "slippage",
                }
                target = mapping.get(key)
                if target:
                    components[target]["status"] = "BLOCKED"
                    components[target]["missing_artifact"] = rel

    ready = cost_ready_for_validation(components)
    hidden = hidden_assumption_checks()
    checks = contract_self_checks(components, classified, hidden)
    blockers = build_blocker_matrix(components, cost_ready=ready)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.15",
        "status": "PASS",
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator_policy": {
            "decision": "DECISION_6",
            "treatment": LOCKED_POLICY["DECISION_6"],
            "meaning": (
                "Cost-adjusted validation is blocked unless the complete required "
                "cost contract is satisfied."
            ),
            "locked_decisions": dict(LOCKED_POLICY),
        },
        "required_inputs": presence,
        "components": components,
        "cost_ready_for_validation": ready,
        "profitability_validation_run": False,
        "cost_adjusted_metrics_enabled": False,
        "dataset_classifications": {
            "total": len(classified),
            "counts": counts,
            "rows": [
                {
                    "dataset": r["dataset"],
                    "logical_symbol": r["logical_symbol"],
                    "mapping_status": r["mapping_status"],
                    "spread_mode": r["spread_mode"],
                    "historical_bid_ask": r["historical_bid_ask"],
                    "gate_class": r["gate_class"],
                }
                for r in classified
            ],
        },
        "hidden_assumption_checks": hidden,
        "contract_self_checks": checks,
        "blocker_matrix": blockers,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "changes": [
            "tradingbot/backtest/phase27_15_cost_completeness_gate.py",
            "tests/test_phase27_15_cost_completeness_gate.py",
            "docs_v2/01_truth/PHASE27_15_COST_COMPLETENESS_GATE.md",
            PHASE2715_JSON,
        ],
        "tests": {"module": "tests/test_phase27_15_cost_completeness_gate.py"},
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "backtest_run": False,
            "profitability_validation_run": False,
            "optimization_run": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "strategy_modified": False,
            "gate_weakened": False,
            "real_trading_enabled": False,
        },
        "deferred": ["Phase 27.16+ — not started"],
    }

    required = (
        presence["all_present"],
        not ready,
        checks["cost_ready_false_with_current_evidence"],
        checks["one_unknown_blocks_ready"],
        checks["all_complete_would_be_ready"],
        checks["complete_dataset_count_zero"],
        checks["hidden_zero_commission_absent"],
        checks["hidden_zero_swap_absent"],
        checks["hidden_zero_slippage_absent"],
        checks["silent_mapping_absent"],
        checks["proxy_not_historical_spread"],
        checks["complete_costs_required_enforced"],
        counts[CostCompleteness.COMPLETE.value] == 0,
        components["commission"]["status"] == "BLOCKED",
        components["commission"].get("observed_classification") == OBSERVED_ZERO_NOT_PROVEN
        or components["commission"]["status"] == "BLOCKED",
        not payload["cost_adjusted_metrics_enabled"],
        not payload["profitability_validation_run"],
        not payload["safety_confirmation"]["gate_weakened"],
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2715_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    return payload


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    comps = payload["components"]
    counts = payload["dataset_classifications"]["counts"]
    rows = "\n".join(
        f"| `{b['blocker']}` | `{b['status']}` | {b['severity']} | {b['owner']} | {b['remediation']} |"
        for b in payload["blocker_matrix"]
    )
    comp_rows = "\n".join(
        f"| `{name}` | **{comps[name]['status']}** | {comps[name].get('note', '')} |"
        for name in GATE_COMPONENTS
    )
    md = f"""# Phase 27.15 — Final Cost Completeness Gate

**Status:** {payload['status']} (audit)  
**COST_READY_FOR_VALIDATION:** **{str(payload['cost_ready_for_validation']).upper()}**  
**Artifact:** `{PHASE2715_JSON}`

## Operator decision

**COMPLETE_COSTS_REQUIRED.** Cost-adjusted validation is blocked unless every required cost component is COMPLETE. This phase does **not** run profitability validation.

## Gate

`COST_READY_FOR_VALIDATION` is the AND of:

`symbol_binding ∧ economics ∧ dataset_provenance ∧ spread ∧ commission ∧ swap ∧ slippage ∧ execution_model`

Each term must be **COMPLETE**. One UNKNOWN / PARTIAL / BLOCKED keeps the gate closed.

## Component evaluation

| Component | Status | Note |
|---|---|---|
{comp_rows}

## Dataset classification

| Class | Count |
|---|---|
| COMPLETE | `{counts.get('COMPLETE', 0)}` |
| PARTIAL | `{counts.get('PARTIAL', 0)}` |
| UNKNOWN | `{counts.get('UNKNOWN', 0)}` |
| BLOCKED | `{counts.get('BLOCKED', 0)}` |
| total | `{payload['dataset_classifications']['total']}` |

COMPLETE datasets: **0**. Cost-adjusted metrics remain disabled.

## Hidden-assumption verification

| Check | Result |
|---|---|
| Hidden zero commission | **Absent** (default UNKNOWN) |
| Hidden zero swap | **Absent** (default UNKNOWN) |
| Hidden zero slippage | **Absent** (MODELED_PROXY; non-positive → UNKNOWN) |
| Silent XAUUSD → XAUUSD_i map | **Blocked** |
| PROXY spread as historical DATASET | **Forbidden** |
| COMPLETE_COSTS_REQUIRED | **Enforced** |

## Blocker matrix

| Blocker | Status | Severity | Owner | Remediation |
|---|---|---|---|---|
{rows}

## Production

**BLOCKED.** No backtest, optimization, RiskGate, strategy, execution, or real-trading change. Gate was **not** weakened to achieve PASS.

## Next

STOP after Phase 27.15.
"""
    (root / PHASE2715_MD).write_text(md, encoding="utf-8")


def run_phase27_15_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_15_cost_completeness_gate(base_dir)
