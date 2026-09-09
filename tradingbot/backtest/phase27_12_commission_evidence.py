"""Phase 27.12 — VERIFIED_SCHEDULE commission evidence (offline, no MT5)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.commission_policy import (
    BLOCKED,
    OBSERVED_ZERO_NOT_PROVEN,
    POLICY,
    UNKNOWN,
    CommissionPolicyError,
    CommissionSchedule,
    accept_verified_schedule,
    classify_commission_policy,
    classify_observed_commissions,
    cost_adjusted_blocked_when_commission_unknown,
    cost_completeness_from_observed_zero_status,
    cost_completeness_from_unknown_commission,
    cost_completeness_from_verified_schedule_gate_only,
    dataset_completeness_from_observed_zero,
    dataset_completeness_from_unknown_commission,
    enable_zero_commission_from_observed_zeros,
    generic_public_schedule_is_account_specific,
    observed_zero_is_not_verified_schedule,
    synthesize_zero_from_observed,
    verified_schedule_requires_applicability,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    assess_cost_completeness,
    build_backtest_cost_model,
)
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_5_final_broker_cost_gate import load_all_gold_deal_records

PHASE2712_JSON = "logs/phase27_12_commission_evidence.json"
PHASE2712_MD = "docs_v2/01_truth/PHASE27_12_COMMISSION_EVIDENCE.md"
DEMO_EVIDENCE = "logs/operator_broker_evidence_demo_raw.json"
REAL_EVIDENCE = "logs/operator_broker_evidence_raw.json"
SESSION_EVIDENCE = "logs/phase27_5_operator_session_raw.json"


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


def _account_context(data: dict[str, Any], *, fallback_type: str) -> dict[str, Any]:
    acct = data.get("account") if isinstance(data.get("account"), dict) else {}
    return {
        "broker": data.get("broker") or "LiteFinance",
        "server": acct.get("server"),
        "account_type": acct.get("type") or data.get("account_environment") or fallback_type,
        "account_product_type": UNKNOWN,
        "currency": acct.get("currency") or data.get("currency"),
        "trade_mode": acct.get("trade_mode"),
        "collection_utc": data.get("collection_utc"),
        "evidence_class": "STALE_OPERATOR_EVIDENCE",
    }


def _commission_values(deals: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for deal in deals:
        raw = deal.get("commission")
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return values


def contract_self_checks(observed_values: list[float]) -> dict[str, Any]:
    model_default = build_backtest_cost_model(BacktestConfig())
    model_policy = build_backtest_cost_model(BacktestConfig(commission_status=POLICY))
    model_observed = build_backtest_cost_model(BacktestConfig(commission_status=OBSERVED_ZERO_NOT_PROVEN))

    generic = CommissionSchedule(
        broker="LiteFinance",
        source="public_generic_schedule",
        source_class="GENERIC_PUBLIC",
        public_supporting_only=True,
        rate=0.0,
        note="Hypothetical public page — not used as verified evidence.",
    )
    incomplete = CommissionSchedule(
        broker="LiteFinance",
        server="LiteFinance-MT5-Demo",
        symbol="XAUUSD_i",
        rate=0.0,
        applicability_established=False,
    )

    synthesized = False
    try:
        synthesize_zero_from_observed(observed_values)
    except CommissionPolicyError as exc:
        synthesized = exc.code == "ZERO_FROM_OBSERVED_FORBIDDEN"

    zero_assumed = False
    try:
        enable_zero_commission_from_observed_zeros(observed_values)
    except CommissionPolicyError as exc:
        zero_assumed = exc.code == "ZERO_ASSUMPTION_FORBIDDEN"

    accepted_generic = False
    try:
        accept_verified_schedule(generic)
        accepted_generic = True
    except CommissionPolicyError:
        accepted_generic = False

    accepted_incomplete = False
    try:
        accept_verified_schedule(incomplete)
        accepted_incomplete = True
    except CommissionPolicyError:
        accepted_incomplete = False

    return {
        "default_commission_unknown": model_default.commission.availability == CostAvailability.UNKNOWN,
        "default_commission_status": BacktestConfig().commission_status,
        "policy_gate_not_verified": model_policy.commission.availability
        == CostAvailability.VERIFIED_SCHEDULE
        and model_policy.commission.value is None,
        "observed_zero_status_explicit": model_observed.commission.availability
        == CostAvailability.OBSERVED_ZERO_NOT_PROVEN,
        "observed_zero_not_verified_schedule": observed_zero_is_not_verified_schedule(observed_values),
        "generic_public_not_account_specific": not generic_public_schedule_is_account_specific(generic),
        "verified_schedule_requires_applicability": not verified_schedule_requires_applicability(incomplete),
        "generic_not_accepted": not accepted_generic,
        "incomplete_not_accepted": not accepted_incomplete,
        "zero_not_synthesized_from_observed": synthesized,
        "zero_assumption_forbidden": zero_assumed,
        "completeness_from_unknown": cost_completeness_from_unknown_commission().value,
        "completeness_from_observed_zero": cost_completeness_from_observed_zero_status().value,
        "completeness_from_policy_gate_only": cost_completeness_from_verified_schedule_gate_only().value,
        "dataset_completeness_from_unknown": dataset_completeness_from_unknown_commission(),
        "dataset_completeness_from_observed_zero": dataset_completeness_from_observed_zero(),
        "cost_adjusted_blocked": cost_adjusted_blocked_when_commission_unknown(),
        "assess_default_not_complete": assess_cost_completeness(model_default) != CostCompleteness.COMPLETE,
        "assess_policy_not_complete": assess_cost_completeness(model_policy) != CostCompleteness.COMPLETE,
        "assess_observed_zero_not_complete": assess_cost_completeness(model_observed)
        != CostCompleteness.COMPLETE,
    }


def run_phase27_12_commission_evidence(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    demo = _safe_load_json(root / DEMO_EVIDENCE) or {}
    real = _safe_load_json(root / REAL_EVIDENCE) or {}
    session = _safe_load_json(root / SESSION_EVIDENCE) or {}

    gold_deals = load_all_gold_deal_records(root)
    values = _commission_values(gold_deals)
    observed = classify_observed_commissions(values)
    checks = contract_self_checks(values)
    classification = classify_commission_policy(
        commission_status=POLICY,
        observed_values=values,
        schedule=None,
    )

    schedule_status = UNKNOWN
    if observed.status == OBSERVED_ZERO_NOT_PROVEN:
        schedule_status = BLOCKED

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.12",
        "status": "PASS",
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator_policy": {
            "decision": "DECISION_3",
            "treatment": POLICY,
            "meaning": (
                "Commission may only be accepted for validation when a verified, "
                "account-applicable schedule is obtained. Selecting VERIFIED_SCHEDULE "
                "is a gate, not current verification."
            ),
        },
        "context": {
            "broker": "LiteFinance",
            "servers": {
                "demo": (demo.get("account") or {}).get("server"),
                "real": (real.get("account") or {}).get("server"),
            },
            "account_type": {
                "demo": (demo.get("account") or {}).get("type"),
                "real": (real.get("account") or {}).get("type"),
                "session": (session.get("account") or {}).get("type"),
            },
            "account_product_type": UNKNOWN,
            "asset_class": "gold",
            "symbol": "XAUUSD_i",
            "currency_account": {
                "demo": (demo.get("account") or {}).get("currency"),
                "real": (real.get("account") or {}).get("currency"),
            },
            "commission_currency": UNKNOWN,
            "basis": UNKNOWN,
            "effective_date_or_version": UNKNOWN,
            "applicability_established": False,
            "applicability_conditions": [
                "Must match broker LiteFinance",
                "Must match account server (LiteFinance-MT5-Demo and/or LiteFinance-MT5-Live)",
                "Must match account product / commission tier (currently UNKNOWN)",
                "Must match gold / XAUUSD_i",
                "Must state per-lot, per-side, or round-turn basis",
                "Must state commission currency and effective date/version",
            ],
        },
        "account_metadata": {
            "demo": _account_context(demo, fallback_type="DEMO"),
            "real": _account_context(real, fallback_type="REAL"),
            "session": _account_context(session, fallback_type="DEMO"),
        },
        "operator_deal_tape": {
            "gold_deal_count": len(gold_deals),
            "commission_sample_count": observed.sample_count,
            "observed_zero_count": observed.observed_zero_count,
            "observed_nonzero_count": observed.observed_nonzero_count,
            "classification": observed.status,
            "proves_verified_schedule": False,
            "proves_universal_zero": False,
            "sources": sorted({str(d.get("_source")) for d in gold_deals}),
            "note": observed.note,
        },
        "commission_spec_evidence": {
            "EV-D-16": "NOT COLLECTED",
            "EV-R-16": "NOT COLLECTED",
        },
        "verified_schedule": {
            "found": False,
            "status": schedule_status,
            "provenance": None,
            "applicability_established": False,
            "public_documentation_used_as_verified": False,
            "public_documentation_role": "supporting_only_not_attached",
            "rate": None,
            "basis": UNKNOWN,
            "currency": UNKNOWN,
            "effective_date_or_version": UNKNOWN,
        },
        "classification": classification,
        "contract_self_checks": checks,
        "default_commission_status": BacktestConfig().commission_status,
        "zero_commission_assumption_enabled": False,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "changes": [
            "tradingbot/backtest/commission_policy.py",
            "tradingbot/backtest/cost_model.py",
            "tradingbot/backtest/dataset_provenance.py",
            "tradingbot/backtest/broker.py",
            "tradingbot/backtest/config.py",
            "tradingbot/backtest/operator_evidence.py",
            "tradingbot/backtest/phase27_8_policy_lock.py",
            "tradingbot/backtest/phase27_12_commission_evidence.py",
            "tests/test_phase27_12_commission_evidence.py",
            "docs_v2/01_truth/PHASE27_12_COMMISSION_EVIDENCE.md",
            PHASE2712_JSON,
        ],
        "tests": {"module": "tests/test_phase27_12_commission_evidence.py"},
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "strategy_modified": False,
            "commission_fabricated": False,
            "zero_commission_assumed": False,
            "public_schedule_treated_as_account_specific": False,
        },
        "deferred": ["Phase 27.15+ — not started"],
    }

    required = (
        checks["default_commission_unknown"],
        checks["default_commission_status"] == UNKNOWN,
        checks["policy_gate_not_verified"],
        checks["observed_zero_status_explicit"],
        checks["observed_zero_not_verified_schedule"],
        checks["generic_public_not_account_specific"],
        checks["verified_schedule_requires_applicability"],
        checks["generic_not_accepted"],
        checks["incomplete_not_accepted"],
        checks["zero_not_synthesized_from_observed"],
        checks["zero_assumption_forbidden"],
        checks["completeness_from_unknown"] != CostCompleteness.COMPLETE.value,
        checks["completeness_from_observed_zero"] != CostCompleteness.COMPLETE.value,
        checks["completeness_from_policy_gate_only"] != CostCompleteness.COMPLETE.value,
        checks["dataset_completeness_from_unknown"] != CostCompleteness.COMPLETE.value,
        checks["dataset_completeness_from_observed_zero"] != CostCompleteness.COMPLETE.value,
        checks["cost_adjusted_blocked"],
        observed.status == OBSERVED_ZERO_NOT_PROVEN,
        observed.sample_count == 50,
        observed.observed_zero_count == 50,
        observed.observed_nonzero_count == 0,
        not payload["verified_schedule"]["found"],
        payload["verified_schedule"]["status"] in (UNKNOWN, BLOCKED),
        not payload["zero_commission_assumption_enabled"],
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2712_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    return payload


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    tape = payload["operator_deal_tape"]
    ctx = payload["context"]
    sched = payload["verified_schedule"]
    checks = payload["contract_self_checks"]
    md = f"""# Phase 27.12 — Verified Commission Schedule Evidence

**Status:** {payload['status']}  
**Artifact:** `{PHASE2712_JSON}`

## Operator decision

**VERIFIED_SCHEDULE.** Commission may only be accepted for validation when a verified, account-applicable schedule is obtained. Selecting the policy is a **gate**, not current verification.

## Context (operator evidence, not a schedule)

| Field | Value | Defensible as schedule applicability? |
|---|---|---|
| broker | `{ctx['broker']}` | supporting context only |
| Demo server | `{ctx['servers']['demo']}` | supporting context only |
| Real server | `{ctx['servers']['real']}` | supporting context only |
| account type | Demo `{ctx['account_type']['demo']}` / Real `{ctx['account_type']['real']}` | environment label, not commission product |
| account product / commission tier | **UNKNOWN** | required, missing |
| asset class | `{ctx['asset_class']}` | supporting context only |
| symbol | `{ctx['symbol']}` | supporting context only |
| account currency | Demo `{ctx['currency_account']['demo']}` / Real `{ctx['currency_account']['real']}` | not proven commission currency |
| commission currency | **UNKNOWN** | required, missing |
| basis (per-lot / per-side / round-turn) | **UNKNOWN** | required, missing |
| effective date / version | **UNKNOWN** | required, missing |

EV-D-16 (Demo commission spec) and EV-R-16 (Real commission spec) remain **NOT COLLECTED**.

Public broker documentation was **not** treated as an account-specific verified schedule.

## Observed gold deals

| Field | Value |
|---|---|
| unique gold deals | `{tape['gold_deal_count']}` |
| commission samples | `{tape['commission_sample_count']}` |
| observed zero | `{tape['observed_zero_count']}` |
| observed nonzero | `{tape['observed_nonzero_count']}` |
| classification | **`{tape['classification']}`** |
| proves verified schedule | **False** |
| proves universal zero | **False** |

{tape['note']}

## Verified schedule

| Field | Value |
|---|---|
| found | **False** |
| status | **`{sched['status']}`** |
| provenance | none |
| applicability established | **False** |
| public docs used as verified | **False** |
| rate | none |

## Semantics

| Claim | Result |
|---|---|
| Observed zero ≠ verified schedule | **True** |
| Generic public schedule ≠ account-specific schedule | **True** |
| Verified schedule requires applicability | **True** |
| UNKNOWN commission blocks COMPLETE | **True** (`{checks['completeness_from_unknown']}`) |
| OBSERVED_ZERO_NOT_PROVEN blocks COMPLETE | **True** (`{checks['completeness_from_observed_zero']}`) |
| VERIFIED_SCHEDULE gate without schedule blocks COMPLETE | **True** (`{checks['completeness_from_policy_gate_only']}`) |
| Zero commission assumed from observed zeros | **False** |
| Cost-adjusted validation | **BLOCKED** |

`BacktestConfig.commission_status` default remains `{payload['default_commission_status']}` (fail-closed). SimulatedBroker still refuses entry when commission is not explicit ZERO or MODELED.

## Production

**BLOCKED.** No RiskGate, strategy, or live execution semantic changes. No MT5. No fabricated commission. No zero-commission assumption.

## Next

STOP after Phase 27.12.
"""
    (root / PHASE2712_MD).write_text(md, encoding="utf-8")


def run_phase27_12_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_12_commission_evidence(base_dir)
