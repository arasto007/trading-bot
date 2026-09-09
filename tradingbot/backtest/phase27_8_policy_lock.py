"""Phase 27.8 — Operator broker policy lock and evidence alignment.

Locks the six operator-selected broker-policy decisions. Does not convert
missing evidence into verified evidence. Does not start MT5, place orders,
or modify strategy / RiskGate / execution / sizing / RR / ML.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.config.live import PRIMARY_SYMBOL, SYMBOL_BY_ENVIRONMENT

PHASE278_JSON = "logs/phase27_8_policy_lock.json"
PHASE278_MD = "docs_v2/01_truth/PHASE27_8_POLICY_LOCK.md"
OPERATOR_POLICY_MD = "docs_v2/01_truth/OPERATOR_BROKER_POLICY_DECISION.md"
PHASE277_JSON = "logs/phase27_7_final_blocker_closure.json"

LOCKED_POLICY: dict[str, str] = {
    "DECISION_1": "XAUUSD_i",
    "DECISION_2": "ONLY_WITH_EXPLICIT_DATASET_MAP",
    "DECISION_3": "VERIFIED_SCHEDULE",
    "DECISION_4": "BROKER_RATE_ONLY",
    "DECISION_5": "MODELED",
    "DECISION_6": "COMPLETE_COSTS_REQUIRED",
}

DECISION_OPTIONS: dict[str, tuple[str, ...]] = {
    "DECISION_1": ("XAUUSD", "XAUUSD_i", "UNDECIDED"),
    "DECISION_2": ("YES", "NO", "ONLY_WITH_EXPLICIT_DATASET_MAP", "UNDECIDED"),
    "DECISION_3": ("VERIFIED_SCHEDULE", "OBSERVED_ZERO_NOT_PROVEN", "CONSERVATIVE_MODEL", "UNDECIDED"),
    "DECISION_4": ("HISTORICAL", "BROKER_RATE_ONLY", "CONSERVATIVE_MODEL", "UNDECIDED"),
    "DECISION_5": ("REALIZED", "MODELED", "UNKNOWN", "UNDECIDED"),
    "DECISION_6": ("COMPLETE_COSTS_REQUIRED", "CONSERVATIVE_COST_SCENARIO_ALLOWED", "UNDECIDED"),
}

DECISION_TITLES: dict[str, str] = {
    "DECISION_1": "Canonical gold symbol",
    "DECISION_2": "May logical XAUUSD datasets be treated as XAUUSD_i?",
    "DECISION_3": "Commission treatment",
    "DECISION_4": "Swap treatment",
    "DECISION_5": "Slippage treatment",
    "DECISION_6": "Validation gate",
}

POLICY_MEANINGS: dict[str, str] = {
    "DECISION_1": (
        "Canonical gold symbol is XAUUSD_i. This does not claim that XAUUSD and "
        "XAUUSD_i are economically equivalent. EV-EQ-01 remains NOT_PROVEN until evidence closes it."
    ),
    "DECISION_2": (
        "Logical XAUUSD datasets may be bound to XAUUSD_i only through an explicit "
        "dataset_symbol_map. Silent automatic treatment of XAUUSD datasets as XAUUSD_i is forbidden."
    ),
    "DECISION_3": (
        "Commission may only be accepted for validation when a verified, account-applicable "
        "schedule is obtained. Selecting VERIFIED_SCHEDULE is a policy gate, not proof that a "
        "verified schedule currently exists."
    ),
    "DECISION_4": (
        "Broker swap rates may be recorded and used where explicitly supported, but historical "
        "swap series must not be invented."
    ),
    "DECISION_5": (
        "Modeled slippage is permitted only when its assumptions, parameters and limitations "
        "are explicitly documented. Modeled slippage must never be represented as realized slippage."
    ),
    "DECISION_6": (
        "Cost-adjusted validation is blocked unless the complete required cost contract is satisfied."
    ),
}

FORBIDDEN_OUTPUT_KEYS = frozenset({"login", "password", "mt5_password", "server_password"})


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


def parse_operator_policy(text: str) -> dict[str, Any]:
    """Parse OPERATOR_BROKER_POLICY_DECISION.md into locked decisions.

    POLICY values come only from checked boxes. Status LOCKED is required for
    Phase 27.8; AWAITING OPERATOR is rejected as stale.
    """
    header = "\n".join(text.splitlines()[:12])
    awaiting = "AWAITING OPERATOR" in header
    locked = bool(re.search(r"\*\*Status:\*\*\s*LOCKED", text)) or ("Status:** LOCKED" in text)
    if not locked and re.search(r"Status:\s*LOCKED", text):
        locked = True

    decisions: dict[str, str] = {}
    sections = re.split(r"(?=^## DECISION \d)", text, flags=re.MULTILINE)
    for block in sections:
        match = re.match(r"## DECISION (\d)", block)
        if not match:
            continue
        key = f"DECISION_{match.group(1)}"
        options = DECISION_OPTIONS.get(key, ())
        selected: list[str] = []
        for opt in options:
            pattern = rf"- \[x\]\s*(?:\*\*)?{re.escape(opt)}(?:\*\*)?(?:\s|$)"
            if re.search(pattern, block, flags=re.IGNORECASE):
                selected.append(opt)
        if len(selected) == 1:
            decisions[key] = selected[0]
        elif not selected:
            decisions[key] = "UNDECIDED"
        else:
            decisions[key] = "AMBIGUOUS:" + ",".join(selected)

    for key in LOCKED_POLICY:
        decisions.setdefault(key, "UNDECIDED")

    all_locked = all(decisions[k] == LOCKED_POLICY[k] for k in LOCKED_POLICY)
    return {
        "status": "LOCKED" if locked and all_locked and not awaiting else (
            "AWAITING_OPERATOR" if awaiting else "INCONSISTENT"
        ),
        "awaiting_operator": awaiting,
        "locked": locked and all_locked and not awaiting,
        "decisions": decisions,
        "matches_operator_selection": all_locked,
    }


def write_operator_policy_md(root: Path) -> str:
    """Write the locked operator policy document. POLICY ≠ EVIDENCE."""
    content = """# Operator Broker Policy Decision

**Status:** LOCKED — Phase 27.8 operator policy lock
**Locked:** 2026-09-06
**Epistemic rule:** POLICY ≠ EVIDENCE. A selected treatment is an acceptance rule, not proof of the corresponding broker fact.

---

## Epistemic distinction

| Layer | Meaning |
|---|---|
| **POLICY** | What the operator decided must be used as the acceptance / validation rule |
| **EVIDENCE** | What the repository has actually proven |

Missing evidence is recorded as a gap. It is never converted into verified evidence because a policy option was selected.

Unchecked **UNDECIDED** options are retained as the rejected alternatives. They are not the selected state.

---

## DECISION 1: Canonical gold symbol

- [ ] XAUUSD
- [x] XAUUSD_i
- [ ] **UNDECIDED**

**POLICY:** Canonical gold symbol is `XAUUSD_i`.

**DOES NOT MEAN:** `XAUUSD` and `XAUUSD_i` are economically equivalent.

**EVIDENCE:** Observed Demo terminal contains `XAUUSD_i` and does not contain `XAUUSD`. Stale Real evidence also showed `XAUUSD_i` and no `XAUUSD`. Absence on observed terminals is not broker-wide proof.

**EV-EQ-01:** **NOT_PROVEN**. Remains NOT_PROVEN until evidence closes it.

---

## DECISION 2: May logical XAUUSD datasets be treated as XAUUSD_i?

- [ ] YES
- [ ] NO
- [x] ONLY_WITH_EXPLICIT_DATASET_MAP
- [ ] **UNDECIDED**

**POLICY:** Logical `XAUUSD` datasets may be bound to `XAUUSD_i` only through an explicit `dataset_symbol_map`.

**FORBIDDEN:** Silent automatic treatment of `XAUUSD` datasets as `XAUUSD_i`. Without an explicit map, `resolve_broker_symbol_for_dataset` must fail closed (`SYMBOL_MISMATCH`).

**EVIDENCE:** Many parquet datasets remain labeled `XAUUSD`. No automatic equivalence is authorized. An empty `dataset_symbol_map` does not create a relationship.

---

## DECISION 3: Commission treatment

- [x] VERIFIED_SCHEDULE
- [ ] OBSERVED_ZERO_NOT_PROVEN
- [ ] CONSERVATIVE_MODEL
- [ ] **UNDECIDED**

**POLICY:** `VERIFIED_SCHEDULE` means commission may only be accepted for validation when a verified, account-applicable schedule is obtained.

**DOES NOT MEAN:** A verified commission schedule currently exists. Selecting `VERIFIED_SCHEDULE` is a gate, not a verification.

**EVIDENCE:** No account-specific verified commission schedule has been established. Observed zero-commission deals do not prove universal zero.

**IMPLEMENTATION (Phase 27.12):** Gate implemented. No account-applicable schedule obtained. 50 gold deals at 0.0 classified `OBSERVED_ZERO_NOT_PROVEN`. Default `commission_status` remains UNKNOWN. Cost completeness remains fail-closed. See `docs_v2/01_truth/PHASE27_12_COMMISSION_EVIDENCE.md`.

---

## DECISION 4: Swap treatment

- [ ] HISTORICAL
- [x] BROKER_RATE_ONLY
- [ ] CONSERVATIVE_MODEL
- [ ] **UNDECIDED**

**POLICY:** `BROKER_RATE_ONLY` means broker swap rates may be recorded and used where explicitly supported, but historical swap series must not be invented.

**EVIDENCE:** Broker swap rates may appear on symbol spec snapshots. Historical swap series remains UNKNOWN. Short-hold zero swap does not prove a zero historical series.

---

## DECISION 5: Slippage treatment

- [ ] REALIZED
- [x] MODELED
- [ ] UNKNOWN
- [ ] **UNDECIDED**

**POLICY:** `MODELED` means modeled slippage is permitted only when its assumptions, parameters and limitations are explicitly documented. It must never be represented as realized slippage.

**EVIDENCE:** Slippage evidence is insufficient for realized historical slippage. MT5 deviation is not realized slippage.

---

## DECISION 6: Validation gate

- [x] COMPLETE_COSTS_REQUIRED
- [ ] CONSERVATIVE_COST_SCENARIO_ALLOWED
- [ ] **UNDECIDED**

**POLICY:** `COMPLETE_COSTS_REQUIRED` means cost-adjusted validation is blocked unless the complete required cost contract is satisfied.

**EVIDENCE:** Cost completeness is not complete. Cost-adjusted metrics remain disabled. Production readiness remains **BLOCKED**.

**IMPLEMENTATION (Phase 27.16):** FINAL_GATE = BLOCKED. Not strategy approval, profitability approval, or real-money authorization. See `docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md`.

---

**Configured code defaults (NOT policy):** `PRIMARY_SYMBOL=XAUUSD_i`, `SYMBOL_BY_ENVIRONMENT` → XAUUSD_i for Demo and Real. Code default alignment with Decision 1 is CONFIGURED, not evidence that EV-EQ-01 is proven.

**Phase 27.8 artifact:** `logs/phase27_8_policy_lock.json`  
**Phase 27.8 document:** `docs_v2/01_truth/PHASE27_8_POLICY_LOCK.md`  
**Phase 27.12 commission evidence:** `logs/phase27_12_commission_evidence.json`  
**Phase 27.16 final validation gate:** `logs/phase27_16_FINAL_VALIDATION_GATE.json`
"""
    path = root / OPERATOR_POLICY_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return content


def silent_xauusd_binding_forbidden() -> dict[str, Any]:
    """Decision 2: XAUUSD must not bind to XAUUSD_i without an explicit map."""
    raised = False
    code = ""
    try:
        resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
    except InstrumentContractError as exc:
        raised = True
        code = exc.code
    explicit_ok = False
    mapped = ""
    source = ""
    try:
        mapped, source = resolve_broker_symbol_for_dataset(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        explicit_ok = mapped == "XAUUSD_i" and source == "explicit_map"
    except InstrumentContractError:
        explicit_ok = False
    return {
        "silent_bind_raised": raised,
        "silent_bind_code": code,
        "explicit_map_permitted": explicit_ok,
        "empty_map_is_not_a_relationship": True,
        "policy": LOCKED_POLICY["DECISION_2"],
    }


def modeled_slippage_is_not_realized(assumptions_documented: bool) -> dict[str, Any]:
    """Decision 5: modeled slippage never counts as realized."""
    return {
        "policy": LOCKED_POLICY["DECISION_5"],
        "modeled_permitted": assumptions_documented,
        "represented_as_realized": False,
        "realized_historical_slippage_proven": False,
        "mt5_deviation_is_slippage": False,
        "requires_documented_assumptions": True,
    }


def verified_schedule_is_gate_not_proof(schedule_obtained: bool) -> dict[str, Any]:
    """Decision 3: VERIFIED_SCHEDULE is an acceptance gate, not current verification."""
    return {
        "policy": LOCKED_POLICY["DECISION_3"],
        "policy_means_verified_schedule_exists": False,
        "account_applicable_schedule_obtained": schedule_obtained,
        "commission_accepted_for_validation": schedule_obtained,
        "observed_zero_is_not_universal_zero": True,
    }


def cost_adjusted_validation_allowed(completeness: CostCompleteness | str) -> bool:
    """Decision 6: cost-adjusted validation requires a complete cost contract."""
    value = completeness.value if isinstance(completeness, CostCompleteness) else str(completeness)
    return value == CostCompleteness.COMPLETE.value


def align_policy_with_evidence(
    policy: dict[str, str],
    inherited: dict[str, Any],
) -> dict[str, Any]:
    """Fail-closed alignment: keep operator policy; record evidence gaps.

    Never silently reconcile a conflict by changing the selected policy.
    """
    ev_eq = str((inherited.get("ev_eq_01") or {}).get("status") or "NOT_PROVEN")
    commission_status = str((inherited.get("commission") or {}).get("status") or "UNKNOWN")
    verified_schedule = bool((inherited.get("commission") or {}).get("verified_schedule"))
    swap_hist = str((inherited.get("swap") or {}).get("historical_swap_series") or "UNKNOWN")
    slip_status = str((inherited.get("slippage") or {}).get("status") or "UNKNOWN")
    slip_n = int((inherited.get("slippage") or {}).get("realized_sample_count") or 0)
    tape = bool((inherited.get("spread") or {}).get("historical_m5_tape_available"))
    complete_count = int((inherited.get("cost_completeness") or {}).get("complete_count") or 0)
    cost_complete = str((inherited.get("cost_completeness") or {}).get("status") or "UNKNOWN")
    real_fresh = bool((inherited.get("real_operator_evidence") or {}).get("fresh_collected"))
    xauusd_n = int((inherited.get("dataset_binding") or {}).get("xauusd_count") or 0)

    rows = [
        {
            "decision": "DECISION_1",
            "policy": policy["DECISION_1"],
            "evidence": "Demo XAUUSD_i present / XAUUSD absent; stale Real same observation",
            "conflict": False,
            "gap": ev_eq != "PROVEN",
            "gap_id": "EV-EQ-01",
            "gap_status": ev_eq,
            "preserved_policy": policy["DECISION_1"],
            "note": "Policy selects XAUUSD_i without claiming equivalence",
        },
        {
            "decision": "DECISION_2",
            "policy": policy["DECISION_2"],
            "evidence": f"{xauusd_n} logical XAUUSD datasets; empty default dataset_symbol_map",
            "conflict": False,
            "gap": xauusd_n > 0,
            "gap_id": "EXPLICIT_DATASET_MAP_ABSENT",
            "gap_status": "REQUIRED_NOT_POPULATED" if xauusd_n > 0 else "NONE",
            "preserved_policy": policy["DECISION_2"],
            "note": "Silent XAUUSD→XAUUSD_i treatment remains forbidden",
        },
        {
            "decision": "DECISION_3",
            "policy": policy["DECISION_3"],
            "evidence": f"commission status={commission_status}; verified_schedule={verified_schedule}",
            "conflict": False,
            "gap": not verified_schedule,
            "gap_id": "ACCOUNT_VERIFIED_COMMISSION_SCHEDULE",
            "gap_status": "MISSING",
            "preserved_policy": policy["DECISION_3"],
            "note": "VERIFIED_SCHEDULE is a gate; missing schedule is not converted into verified evidence",
        },
        {
            "decision": "DECISION_4",
            "policy": policy["DECISION_4"],
            "evidence": f"historical_swap_series={swap_hist}",
            "conflict": False,
            "gap": swap_hist in ("UNKNOWN", "", "None"),
            "gap_id": "HISTORICAL_SWAP_SERIES",
            "gap_status": swap_hist,
            "preserved_policy": policy["DECISION_4"],
            "note": "Broker rates may be recorded; historical series must not be invented",
        },
        {
            "decision": "DECISION_5",
            "policy": policy["DECISION_5"],
            "evidence": f"slippage status={slip_status}; realized_sample_count={slip_n}",
            "conflict": False,
            "gap": slip_status != "REALIZED" or slip_n <= 0,
            "gap_id": "REALIZED_SLIPPAGE",
            "gap_status": slip_status,
            "preserved_policy": policy["DECISION_5"],
            "note": "MODELED is permitted only with documented assumptions; not represented as realized",
        },
        {
            "decision": "DECISION_6",
            "policy": policy["DECISION_6"],
            "evidence": f"cost_completeness={cost_complete}; complete_count={complete_count}; historical_m5_tape={tape}",
            "conflict": False,
            "gap": complete_count == 0 or cost_complete != CostCompleteness.COMPLETE.value,
            "gap_id": "COST_CONTRACT_INCOMPLETE",
            "gap_status": cost_complete,
            "preserved_policy": policy["DECISION_6"],
            "note": "Cost-adjusted validation remains blocked",
        },
    ]

    extra_gaps = []
    if not real_fresh:
        extra_gaps.append(
            {
                "gap_id": "FRESH_REAL_MT5_EVIDENCE",
                "status": "MISSING",
                "note": "Fresh Real evidence is still required; Demo is not Real",
            }
        )
    if not tape:
        extra_gaps.append(
            {
                "gap_id": "HISTORICAL_M5_BIDASK",
                "status": "MISSING",
                "note": "Historical bid/ask M5 data is not yet available",
            }
        )

    return {
        "rule": "PRESERVE_OPERATOR_POLICY_RECORD_EVIDENCE_GAP",
        "policy_changed_to_fit_evidence": False,
        "rows": rows,
        "extra_gaps": extra_gaps,
        "any_conflict_reconciled": False,
    }


def remaining_blockers(alignment: dict[str, Any], inherited: dict[str, Any]) -> list[dict[str, str]]:
    blockers = [
        {
            "blocker": "EV-EQ-01",
            "status": "NOT_PROVEN",
            "class": "EVIDENCE",
            "note": "Decision 1 does not close equivalence",
        },
        {
            "blocker": "Explicit dataset_symbol_map for logical XAUUSD datasets",
            "status": "REQUIRED_NOT_POPULATED",
            "class": "EVIDENCE",
            "note": "Decision 2 locks the rule; it does not populate maps",
        },
        {
            "blocker": "Account-applicable verified commission schedule",
            "status": "MISSING",
            "class": "EVIDENCE",
            "note": "Decision 3 VERIFIED_SCHEDULE is a gate, not current verification",
        },
        {
            "blocker": "Historical swap series",
            "status": "UNKNOWN",
            "class": "EVIDENCE",
            "note": "Decision 4 forbids inventing a series",
        },
        {
            "blocker": "Realized historical slippage",
            "status": "INSUFFICIENT",
            "class": "EVIDENCE",
            "note": "Decision 5 MODELED is not realized slippage",
        },
        {
            "blocker": "Historical M5 bid/ask tape",
            "status": "MISSING",
            "class": "EVIDENCE",
            "note": "Required for DATASET spread completeness",
        },
        {
            "blocker": "Cost completeness COMPLETE",
            "status": "NOT_COMPLETE",
            "class": "EVIDENCE",
            "note": "Decision 6 blocks cost-adjusted validation",
        },
        {
            "blocker": "Fresh Real MT5 evidence",
            "status": "MISSING" if not bool((inherited.get("real_operator_evidence") or {}).get("fresh_collected")) else "COLLECTED",
            "class": "EVIDENCE",
            "note": "Stale Real observations are not fresh Real evidence",
        },
        {
            "blocker": "Production readiness",
            "status": "BLOCKED",
            "class": "GATE",
            "note": "Policy lock does not authorize production",
        },
    ]
    closed_by_policy = [
        {
            "blocker": "Operator policy pack (six decisions)",
            "status": "LOCKED",
            "class": "POLICY",
            "note": "No longer AWAITING OPERATOR",
        },
        {
            "blocker": "Canonical symbol policy selection",
            "status": "LOCKED",
            "class": "POLICY",
            "note": "XAUUSD_i selected; equivalence still NOT_PROVEN",
        },
    ]
    return blockers + closed_by_policy


def inherit_evidence(root: Path) -> dict[str, Any]:
    """Read Phase 27.7 artifact if present. Do not re-probe MT5."""
    raw = _safe_load_json(root / PHASE277_JSON) or {}
    return {
        "source": PHASE277_JSON if raw else None,
        "ev_eq_01": raw.get("ev_eq_01") or {"status": "NOT_PROVEN"},
        "commission": raw.get("commission")
        or {"status": "UNKNOWN", "verified_schedule": False, "tier": "UNKNOWN"},
        "swap": raw.get("swap") or {"historical_swap_series": "UNKNOWN"},
        "slippage": raw.get("slippage") or {"status": "UNKNOWN", "realized_sample_count": 0},
        "spread": raw.get("spread") or {"historical_m5_tape_available": False},
        "cost_completeness": raw.get("cost_completeness")
        or {"status": CostCompleteness.UNKNOWN.value, "complete_count": 0, "forced_complete": False},
        "real_operator_evidence": raw.get("real_operator_evidence")
        or {"fresh_collected": False, "status": "BLOCKED_PENDING_OPERATOR"},
        "dataset_binding": raw.get("dataset_binding") or {"xauusd_count": 0, "xauusd_i_count": 0},
        "production_authorized": bool(raw.get("production_authorized")),
    }


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def run_phase27_8_policy_lock(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    write_operator_policy_md(root)
    text = (root / OPERATOR_POLICY_MD).read_text(encoding="utf-8")
    parsed = parse_operator_policy(text)
    inherited = inherit_evidence(root)
    alignment = align_policy_with_evidence(LOCKED_POLICY, inherited)
    blockers = remaining_blockers(alignment, inherited)
    binding = silent_xauusd_binding_forbidden()
    schedule = verified_schedule_is_gate_not_proof(False)
    slip = modeled_slippage_is_not_realized(True)
    model = build_backtest_cost_model(BacktestConfig())
    dummy = BacktestResult(
        config=BacktestConfig(),
        initial_balance=1000.0,
        final_balance=1000.0,
        trades=[],
        equity_curve=[{"equity": 1000.0}],
    )
    metrics_unknown = compute_metrics(dummy, cost_completeness=CostCompleteness.UNKNOWN)
    metrics_complete = compute_metrics(dummy, cost_completeness=CostCompleteness.COMPLETE)

    complete_count = int((inherited.get("cost_completeness") or {}).get("complete_count") or 0)
    cost_ready = False
    production_blocked = True

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.8",
        "status": "LOCKED",
        "policy_status": parsed["status"],
        "awaiting_operator": False,
        "policy_is_not_evidence": True,
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator_policy": {
            "artifact": OPERATOR_POLICY_MD,
            "status": "LOCKED",
            "awaiting_operator": False,
            "decisions": dict(LOCKED_POLICY),
            "parsed": parsed,
            "meanings": dict(POLICY_MEANINGS),
            "titles": dict(DECISION_TITLES),
        },
        "policy_vs_evidence": {
            "rule": "POLICY_IS_NOT_EVIDENCE",
            "decision_3_verified_schedule_is_not_current_verification": True,
            "decision_1_does_not_claim_equivalence": True,
            "ev_eq_01": "NOT_PROVEN",
            "decision_2_forbids_silent_xauusd_binding": True,
            "decision_4_forbids_invented_historical_swap": True,
            "decision_5_modeled_is_not_realized": True,
            "decision_6_blocks_incomplete_cost_validation": True,
        },
        "alignment": alignment,
        "binding_semantics": binding,
        "commission_gate": schedule,
        "slippage_semantics": slip,
        "cost_gate": {
            "policy": LOCKED_POLICY["DECISION_6"],
            "unknown_allows_cost_adjusted": cost_adjusted_validation_allowed(CostCompleteness.UNKNOWN),
            "complete_allows_cost_adjusted": cost_adjusted_validation_allowed(CostCompleteness.COMPLETE),
            "metrics_unknown_cost_adjusted": bool(metrics_unknown.get("cost_adjusted_metrics")),
            "metrics_complete_cost_adjusted": bool(metrics_complete.get("cost_adjusted_metrics")),
            "default_commission_availability": model.commission.availability.value,
            "complete_dataset_count": complete_count,
            "cost_ready_for_validation": cost_ready,
        },
        "inherited_evidence": {
            "source": inherited.get("source"),
            "ev_eq_01": inherited["ev_eq_01"].get("status", "NOT_PROVEN"),
            "commission_status": inherited["commission"].get("status", "UNKNOWN"),
            "verified_schedule": bool(inherited["commission"].get("verified_schedule")),
            "historical_swap_series": inherited["swap"].get("historical_swap_series", "UNKNOWN"),
            "slippage_status": inherited["slippage"].get("status", "UNKNOWN"),
            "realized_slippage_samples": inherited["slippage"].get("realized_sample_count", 0),
            "historical_m5_bidask": bool(inherited["spread"].get("historical_m5_tape_available")),
            "cost_completeness": inherited["cost_completeness"].get("status", "UNKNOWN"),
            "complete_count": complete_count,
            "fresh_real_evidence": bool(inherited["real_operator_evidence"].get("fresh_collected")),
            "xauusd_dataset_count": inherited["dataset_binding"].get("xauusd_count", 0),
            "configured_primary_symbol": PRIMARY_SYMBOL,
            "symbol_by_environment": SYMBOL_BY_ENVIRONMENT,
        },
        "evidence_still_missing": [
            "EV-EQ-01 (XAUUSD ↔ XAUUSD_i equivalence) NOT_PROVEN",
            "Account-specific verified commission schedule",
            "Historical swap series (must not be invented)",
            "Historical M5 bid/ask tape",
            "Realized historical slippage distribution",
            "Cost completeness COMPLETE (0 datasets)",
            "Fresh Real MT5 operator evidence",
            "Explicit dataset_symbol_map entries for logical XAUUSD datasets",
        ],
        "blockers_remaining": blockers,
        "policy_closed": [
            "Six operator broker-policy decisions locked",
            "AWAITING OPERATOR status removed",
            "Canonical symbol policy = XAUUSD_i",
            "Silent XAUUSD→XAUUSD_i treatment forbidden",
        ],
        "production_readiness": "BLOCKED",
        "production_authorized": False,
        "production_changes": "NONE",
        "cost_ready_for_validation": False,
        "configured": [
            f"PRIMARY_SYMBOL={PRIMARY_SYMBOL}",
            f"SYMBOL_BY_ENVIRONMENT={SYMBOL_BY_ENVIRONMENT}",
        ],
        "proven": [
            "Operator selected the six decisions listed in LOCKED_POLICY",
            "Observed Demo contains XAUUSD_i and does not contain XAUUSD (inherited observation)",
        ],
        "unknown": [
            "EV-EQ-01 equivalence",
            "Account-applicable commission schedule",
            "Historical swap series",
            "Realized slippage",
            "Fresh Real economics",
        ],
        "deferred": ["Phase 27.9+ evidence closure — not started"],
        "changes": [
            "docs_v2/01_truth/OPERATOR_BROKER_POLICY_DECISION.md",
            "docs_v2/01_truth/PHASE27_8_POLICY_LOCK.md",
            "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
            "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
            "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md",
            "docs_v2/01_truth/PHASE27_7_FINAL_BLOCKER_CLOSURE.md",
            "tradingbot/backtest/phase27_8_policy_lock.py",
            "tests/test_phase27_8_policy_lock.py",
            PHASE278_JSON,
        ],
        "tests": {"module": "tests/test_phase27_8_policy_lock.py"},
        "safety_confirmation": {
            "mt5_started": False,
            "symbol_select": False,
            "orders_sent": False,
            "credentials_accessed": False,
            "env_modified": False,
            "datasets_modified": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "sizing_modified": False,
            "rr_modified": False,
            "ml_modified": False,
            "trading_enabled": False,
            "evidence_fabricated": False,
        },
    }
    payload = _sanitize(payload)
    out = root / PHASE278_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    return payload


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    decisions = payload["operator_policy"]["decisions"]
    ev = payload["inherited_evidence"]
    missing = payload["evidence_still_missing"]
    blockers = payload["blockers_remaining"]
    missing_list = "\n".join(f"- {item}" for item in missing)
    blocker_rows = "\n".join(
        f"| {b['blocker']} | {b['status']} | {b['class']} | {b['note']} |" for b in blockers
    )
    md = f"""# Phase 27.8 — Operator Policy Lock & Evidence Alignment

**Status:** {payload['status']}  
**Artifact:** `{PHASE278_JSON}`  
**Policy document:** `{OPERATOR_POLICY_MD}`

## Objective

Convert the operator's six selected broker-policy decisions into a formally locked, internally consistent policy document. Do **not** convert missing evidence into verified evidence.

## Epistemic rule

**POLICY ≠ EVIDENCE.** If repository evidence conflicts with the selected policy, preserve the operator policy and record the evidence gap. Never silently reconcile it.

## Locked policy decisions

| # | Topic | POLICY (operator) | EVIDENCE (repository) |
|---|---|---|---|
| 1 | Canonical gold symbol | `{decisions['DECISION_1']}` | Demo/stale Real show XAUUSD_i present, XAUUSD absent. EV-EQ-01 **{ev['ev_eq_01']}** |
| 2 | Logical XAUUSD datasets | `{decisions['DECISION_2']}` | Silent bind forbidden. Explicit map required; maps not populated |
| 3 | Commission | `{decisions['DECISION_3']}` | Status {ev['commission_status']}. Verified schedule = {ev['verified_schedule']}. Gate ≠ proof |
| 4 | Swap | `{decisions['DECISION_4']}` | historical_swap_series = {ev['historical_swap_series']}. Series must not be invented |
| 5 | Slippage | `{decisions['DECISION_5']}` | Status {ev['slippage_status']}; realized samples = {ev['realized_slippage_samples']}. MODELED ≠ realized |
| 6 | Validation gate | `{decisions['DECISION_6']}` | Cost completeness {ev['cost_completeness']}; complete datasets = {ev['complete_count']} |

## Decision semantics

1. **XAUUSD_i** is the canonical gold symbol. It does **not** claim `XAUUSD` ≡ `XAUUSD_i`. EV-EQ-01 remains NOT_PROVEN.
2. **ONLY_WITH_EXPLICIT_DATASET_MAP** forbids silent automatic treatment of logical XAUUSD datasets as XAUUSD_i.
3. **VERIFIED_SCHEDULE** means commission may only be accepted for validation when a verified, account-applicable schedule is obtained. It does **not** mean a schedule has been verified.
4. **BROKER_RATE_ONLY** allows recorded broker swap rates where explicitly supported. Historical swap series must not be invented.
5. **MODELED** permits modeled slippage only with documented assumptions, parameters and limitations. It must never be represented as realized slippage.
6. **COMPLETE_COSTS_REQUIRED** blocks cost-adjusted validation unless the complete required cost contract is satisfied.

## AWAITING OPERATOR

Removed. The six decisions are locked. Remaining work is evidence closure, not policy selection.

## Evidence still missing

{missing_list}

## Blockers remaining

| Blocker | Status | Class | Note |
|---|---|---|---|
{blocker_rows}

## Production

**BLOCKED** — `production_changes: NONE`. Policy lock does not enable trading, start MT5, place orders, alter `.env`, or modify Strategy / RiskGate / execution / sizing / RR / ML.

## Next

STOP after Phase 27.8. Do not begin Phase 27.9+.
"""
    (root / PHASE278_MD).write_text(md, encoding="utf-8")


def run_phase27_8_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_8_policy_lock(base_dir)
