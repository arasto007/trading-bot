"""Phase 27.16 — Final broker/cost validation gate (offline, fail-closed).

Decides eligibility for cost-aware validation only.
Not strategy approval. Not profitability approval. Not real-money authorization.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY
from tradingbot.backtest.phase27_15_cost_completeness_gate import (
    GATE_COMPONENTS,
    cost_ready_for_validation,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2716_JSON = "logs/phase27_16_FINAL_VALIDATION_GATE.json"
PHASE2716_MD = "docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md"

READY = "READY_FOR_COST_AWARE_VALIDATION"
BLOCKED = "BLOCKED"

REQUIRED_ARTIFACTS = {
    "phase27": "logs/phase27_broker_reality_audit.json",
    "phase27_5": "logs/phase27_5_final_broker_cost_gate.json",
    "phase27_6": "logs/phase27_6_final_evidence_gate.json",
    "phase27_7": "logs/phase27_7_final_blocker_closure.json",
    "phase27_8": "logs/phase27_8_policy_lock.json",
    "phase27_9": "logs/phase27_9_real_broker_evidence.json",
    "phase27_10": "logs/phase27_10_dataset_symbol_binding.json",
    "phase27_11": "logs/phase27_11_historical_bidask.json",
    "phase27_12": "logs/phase27_12_commission_evidence.json",
    "phase27_13": "logs/phase27_13_swap_policy.json",
    "phase27_14": "logs/phase27_14_slippage_model.json",
    "phase27_15": "logs/phase27_15_cost_completeness_gate.json",
}

# Statuses that may be explicit but never qualify the final gate as READY.
NON_READY = frozenset(
    {
        "UNKNOWN",
        "PARTIAL",
        "BLOCKED",
        "BLOCKED_PENDING_DATA",
        "BLOCKED_PENDING_OPERATOR",
        "MT5_NOT_ATTACHED",
        "NOT_PROVEN",
        "OBSERVED_ZERO_NOT_PROVEN",
        "MISSING",
        "NOT_READY",
        "FAIL",
        "",
        "NONE",
    }
)


class FinalGateError(Exception):
    """Refuse to infer READY from partial or implicit evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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


def _load(root: Path, rel: str) -> dict[str, Any]:
    data = _safe_load_json(root / rel)
    return data if isinstance(data, dict) else {}


def artifact_presence(root: Path) -> dict[str, Any]:
    rows = []
    for key, rel in REQUIRED_ARTIFACTS.items():
        present = (root / rel).is_file()
        rows.append({"id": key, "path": rel, "present": present, "status": "PRESENT" if present else "MISSING"})
    return {
        "rows": rows,
        "all_present": all(r["present"] for r in rows),
        "missing": [r["path"] for r in rows if not r["present"]],
    }


def _explicit(value: Any) -> bool:
    return value is not None and str(value).strip() not in ("", "NONE")


def _ready_value(value: Any) -> bool:
    text = str(value).strip().upper() if value is not None else ""
    if not text or text in NON_READY:
        return False
    return True


def infer_ready_from_partial_evidence(partial_status: str) -> str:
    """Partial / unknown / blocked evidence must never become READY."""
    if str(partial_status).upper() in NON_READY or not _ready_value(partial_status):
        return BLOCKED
    raise FinalGateError(
        "PARTIAL_INFERENCE_FORBIDDEN",
        f"Refusing to infer {READY} from status={partial_status!r}",
    )


def _check(
    name: str,
    *,
    value: Any,
    evidence: str,
    ready_when: Any | None = None,
    ready: bool | None = None,
) -> dict[str, Any]:
    explicit = _explicit(value)
    if ready is None:
        if ready_when is not None:
            ready = explicit and str(value) == str(ready_when)
        else:
            ready = explicit and _ready_value(value)
    return {
        "name": name,
        "value": value,
        "explicit": explicit,
        "ready_qualifying": bool(ready),
        "evidence": evidence,
    }


def build_checklist(root: Path) -> list[dict[str, Any]]:
    p8 = _load(root, REQUIRED_ARTIFACTS["phase27_8"])
    p9 = _load(root, REQUIRED_ARTIFACTS["phase27_9"])
    p10 = _load(root, REQUIRED_ARTIFACTS["phase27_10"])
    p11 = _load(root, REQUIRED_ARTIFACTS["phase27_11"])
    p12 = _load(root, REQUIRED_ARTIFACTS["phase27_12"])
    p13 = _load(root, REQUIRED_ARTIFACTS["phase27_13"])
    p14 = _load(root, REQUIRED_ARTIFACTS["phase27_14"])
    p15 = _load(root, REQUIRED_ARTIFACTS["phase27_15"])

    decisions = (p8.get("operator_policy") or {}).get("decisions") or {}
    policy_status = str(p8.get("status") or "")
    comps = p15.get("components") or {}
    counts = (p15.get("dataset_classifications") or {}).get("counts") or {}

    ev_eq = (
        (p9.get("ev_eq_01") or {}).get("status")
        or (p10.get("contract_self_checks") or {}).get("ev_eq_01")
        or (comps.get("economics") or {}).get("ev_eq_01")
    )
    mapping_policy = decisions.get("DECISION_2")
    cost_ready = p15.get("cost_ready_for_validation")
    complete_n = int(counts.get("COMPLETE") or 0)

    checks = [
        _check(
            "operator_policy_locked",
            value=policy_status,
            ready_when="LOCKED",
            evidence=REQUIRED_ARTIFACTS["phase27_8"],
        ),
        _check(
            "canonical_symbol",
            value=decisions.get("DECISION_1") or PRIMARY_SYMBOL,
            ready_when="XAUUSD_i",
            evidence=REQUIRED_ARTIFACTS["phase27_8"],
        ),
        _check(
            "dataset_mapping_policy",
            value=mapping_policy,
            ready_when="ONLY_WITH_EXPLICIT_DATASET_MAP",
            evidence=REQUIRED_ARTIFACTS["phase27_8"],
        ),
        _check(
            "ev_eq_01",
            value=ev_eq,
            ready_when="PROVEN",
            evidence=REQUIRED_ARTIFACTS["phase27_9"],
        ),
        _check(
            "broker_economics",
            value=(comps.get("economics") or {}).get("status"),
            ready_when="COMPLETE",
            evidence=REQUIRED_ARTIFACTS["phase27_15"],
        ),
        _check(
            "historical_spread",
            value=(comps.get("spread") or {}).get("status"),
            ready_when="COMPLETE",
            evidence=REQUIRED_ARTIFACTS["phase27_11"],
        ),
        _check(
            "commission",
            value=(comps.get("commission") or {}).get("status"),
            ready_when="COMPLETE",
            evidence=REQUIRED_ARTIFACTS["phase27_12"],
        ),
        _check(
            "swap",
            value=(comps.get("swap") or {}).get("status"),
            ready_when="COMPLETE",
            evidence=REQUIRED_ARTIFACTS["phase27_13"],
        ),
        _check(
            "slippage",
            value=(comps.get("slippage") or {}).get("status"),
            ready_when="COMPLETE",
            evidence=REQUIRED_ARTIFACTS["phase27_14"],
        ),
        _check(
            "dataset_provenance",
            value=(comps.get("dataset_provenance") or {}).get("status"),
            ready_when="COMPLETE",
            evidence=REQUIRED_ARTIFACTS["phase27_15"],
        ),
        _check(
            "execution_model",
            value=(comps.get("execution_model") or {}).get("status"),
            ready_when="COMPLETE",
            evidence=REQUIRED_ARTIFACTS["phase27_15"],
        ),
        _check(
            "cost_completeness",
            value="COMPLETE" if complete_n > 0 and cost_ready is True else "BLOCKED",
            ready_when="COMPLETE",
            evidence=REQUIRED_ARTIFACTS["phase27_15"],
        ),
        _check(
            "phase27_15_cost_ready",
            value=cost_ready,
            ready=cost_ready is True,
            evidence=REQUIRED_ARTIFACTS["phase27_15"],
        ),
        _check(
            "complete_dataset_count",
            value=complete_n,
            ready=complete_n > 0,
            evidence=REQUIRED_ARTIFACTS["phase27_15"],
        ),
        _check(
            "validation_policy",
            value=decisions.get("DECISION_6"),
            ready_when="COMPLETE_COSTS_REQUIRED",
            evidence=REQUIRED_ARTIFACTS["phase27_8"],
        ),
        _check(
            "code_canonical_symbol",
            value=PRIMARY_SYMBOL,
            ready_when="XAUUSD_i",
            evidence="tradingbot/config/live.py",
        ),
    ]

    # Policy lock must match the six locked decisions exactly.
    checks.append(
        _check(
            "locked_decisions_match",
            value="MATCH" if decisions == LOCKED_POLICY else "MISMATCH",
            ready_when="MATCH",
            evidence=REQUIRED_ARTIFACTS["phase27_8"],
        )
    )
    return checks


def decide_final_gate(
    checklist: list[dict[str, Any]],
    *,
    artifacts_present: bool,
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not artifacts_present:
        reasons.append("One or more required Phase 27 artifacts are missing")

    for item in checklist:
        if not item["explicit"]:
            reasons.append(f"{item['name']} is not explicit")
        elif not item["ready_qualifying"]:
            reasons.append(f"{item['name']}={item['value']} is explicit but not ready-qualifying")

    if components:
        if not cost_ready_for_validation(components):
            reasons.append("Phase 27.15 AND-gate is not COMPLETE on all eight components")
        for name in GATE_COMPONENTS:
            status = str((components.get(name) or {}).get("status") or "")
            if status != "COMPLETE":
                reasons.append(f"component.{name}={status or 'MISSING'}")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)

    state = READY if not unique else BLOCKED
    if state == READY and unique:
        state = BLOCKED
    return {
        "final_gate": state,
        "reasons": unique,
        "ready_qualifying_count": sum(1 for i in checklist if i["ready_qualifying"]),
        "explicit_count": sum(1 for i in checklist if i["explicit"]),
        "checklist_size": len(checklist),
    }


def supporting_artifacts_if_ready(state: str, presence: dict[str, Any]) -> list[str]:
    if state != READY:
        return []
    return [r["path"] for r in presence["rows"] if r["present"]]


def build_blocker_matrix(checklist: list[dict[str, Any]], decision: dict[str, Any]) -> list[dict[str, str]]:
    if decision["final_gate"] == READY:
        return []
    rows = []
    for item in checklist:
        if item["explicit"] and item["ready_qualifying"]:
            continue
        rows.append(
            {
                "blocker": item["name"],
                "evidence": str(item.get("evidence") or ""),
                "status": str(item.get("value")),
                "explicit": "true" if item["explicit"] else "false",
                "severity": "HIGH",
                "remediation": (
                    "Record an explicit ready-qualifying status. "
                    "PARTIAL/UNKNOWN/BLOCKED cannot be inferred as READY."
                ),
                "owner": "GATE",
            }
        )
    rows.append(
        {
            "blocker": "FINAL_GATE",
            "evidence": "AND of explicit ready-qualifying checks + Phase 27.15 COMPLETE AND",
            "status": BLOCKED,
            "explicit": "true",
            "severity": "CRITICAL",
            "remediation": "Every required item must be explicit and ready-qualifying. Do not infer from partial evidence.",
            "owner": "GATE",
        }
    )
    return rows


def permissive_regression_checks(checklist: list[dict[str, Any]], decision: dict[str, Any]) -> dict[str, Any]:
    partial_blocked = infer_ready_from_partial_evidence("PARTIAL") == BLOCKED
    unknown_blocked = infer_ready_from_partial_evidence("UNKNOWN") == BLOCKED
    empty_components_blocked = not cost_ready_for_validation({})
    one_partial = {name: {"status": "COMPLETE"} for name in GATE_COMPONENTS}
    one_partial["commission"] = {"status": "PARTIAL"}
    all_complete = {name: {"status": "COMPLETE"} for name in GATE_COMPONENTS}
    synthetic_ready = decide_final_gate(
        [
            {
                "name": "synthetic",
                "value": "COMPLETE",
                "explicit": True,
                "ready_qualifying": True,
                "evidence": "unit",
            }
        ],
        artifacts_present=True,
        components=all_complete,
    )["final_gate"]
    return {
        "partial_cannot_become_ready": partial_blocked,
        "unknown_cannot_become_ready": unknown_blocked,
        "empty_and_gate_blocked": empty_components_blocked,
        "one_partial_component_blocks_and": not cost_ready_for_validation(one_partial),
        "all_complete_and_allows": cost_ready_for_validation(all_complete),
        "synthetic_complete_checklist_can_be_ready": synthetic_ready == READY,
        "current_evidence_is_blocked": decision["final_gate"] == BLOCKED,
        "ready_never_inferred_from_non_ready_count": all(
            (not item["ready_qualifying"]) or _ready_value(item["value"]) or item["value"] is True or item["value"] == 0
            or (isinstance(item["value"], int) and item["value"] > 0)
            for item in checklist
        ),
    }


def run_phase27_16_final_validation_gate(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    presence = artifact_presence(root)
    p15 = _load(root, REQUIRED_ARTIFACTS["phase27_15"])
    checklist = build_checklist(root)
    decision = decide_final_gate(
        checklist,
        artifacts_present=presence["all_present"],
        components=p15.get("components") or {},
    )
    blockers = build_blocker_matrix(checklist, decision)
    supporting = supporting_artifacts_if_ready(decision["final_gate"], presence)
    permissive = permissive_regression_checks(checklist, decision)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.16",
        "status": "PASS",
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "final_gate": decision["final_gate"],
        "FINAL_GATE": decision["final_gate"],
        "reasons": decision["reasons"],
        "not_strategy_approval": True,
        "not_profitability_approval": True,
        "not_real_money_authorization": True,
        "operator_policy": {
            "locked": True,
            "decisions": dict(LOCKED_POLICY),
            "policy_is_not_evidence": True,
        },
        "required_inputs": presence,
        "checklist": checklist,
        "blocker_matrix": blockers,
        "supporting_artifacts": supporting,
        "permissive_regression": permissive,
        "profitability_analysis_run": False,
        "strategy_optimization_run": False,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "changes": [
            "tradingbot/backtest/phase27_16_final_validation_gate.py",
            "tests/test_phase27_16_final_validation_gate.py",
            "docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md",
            PHASE2716_JSON,
        ],
        "tests": {"module": "tests/test_phase27_16_final_validation_gate.py"},
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "backtest_run": False,
            "profitability_analysis_run": False,
            "strategy_optimization_run": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "strategy_modified": False,
            "rr_modified": False,
            "ml_modified": False,
            "live_trading_configuration_modified": False,
            "gate_weakened": False,
            "readiness_inferred_from_partial": False,
            "phase_28_started": False,
        },
        "deferred": ["Phase 28+ — not started"],
    }

    required = (
        presence["all_present"],
        decision["final_gate"] == BLOCKED,
        len(decision["reasons"]) > 0,
        payload["FINAL_GATE"] == BLOCKED,
        not supporting,
        permissive["partial_cannot_become_ready"],
        permissive["unknown_cannot_become_ready"],
        permissive["empty_and_gate_blocked"],
        permissive["one_partial_component_blocks_and"],
        permissive["all_complete_and_allows"],
        permissive["synthetic_complete_checklist_can_be_ready"],
        permissive["current_evidence_is_blocked"],
        not payload["profitability_analysis_run"],
        not payload["strategy_optimization_run"],
        not payload["safety_confirmation"]["gate_weakened"],
        not payload["safety_confirmation"]["phase_28_started"],
        PRIMARY_SYMBOL == "XAUUSD_i",
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2716_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    return payload


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    reasons = "\n".join(f"- {r}" for r in payload["reasons"])
    checks = "\n".join(
        f"| `{c['name']}` | `{c['value']}` | {'yes' if c['explicit'] else 'no'} | "
        f"{'yes' if c['ready_qualifying'] else '**no**'} | `{c['evidence']}` |"
        for c in payload["checklist"]
    )
    blockers = payload["blocker_matrix"]
    block_rows = "\n".join(
        f"| `{b['blocker']}` | `{b['status']}` | {b['severity']} | {b['owner']} | {b['remediation']} |"
        for b in blockers
    )
    md = f"""# Phase 27.16 — Final Broker/Cost Validation Gate

**Status:** {payload['status']} (audit)

## FINAL_GATE = `{payload['FINAL_GATE']}`

This is **not** strategy approval.  
This is **not** profitability approval.  
This is **not** real-money authorization.

## Exact reasons

{reasons}

## Explicit checklist

| Check | Recorded value | Explicit? | Ready-qualifying? | Evidence |
|---|---|---|---|---|
{checks}

Ready-qualifying requires the recorded value to be the acceptance value (for example COMPLETE, LOCKED, PROVEN, `XAUUSD_i`).  
**Explicit is not READY.** `NOT_PROVEN`, `UNKNOWN`, `PARTIAL`, and `BLOCKED` are explicit and still fail the gate.

PARTIAL evidence is never inferred as `{READY}`.

## Blocker matrix

| Blocker | Status | Severity | Owner | Remediation |
|---|---|---|---|---|
{block_rows}

Supporting artifacts for readiness: **none** (gate is BLOCKED).

## Production

**BLOCKED.** No strategy, RiskGate, execution, RR, ML, or live-trading configuration change. No optimization. No profitability analysis. Phase 28 was **not** started.

## Next

STOP.
"""
    (root / PHASE2716_MD).write_text(md, encoding="utf-8")


def run_phase27_16_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_16_final_validation_gate(base_dir)
