"""Phase 27.19 — account-applicable commission schedule closure.

Offline. Observed commission=0.0 remains OBSERVED_ZERO_NOT_PROVEN.
Public LiteFinance pages are supporting evidence only.
"""

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
    accept_account_applicable_schedule,
    accept_verified_schedule,
    broker_name_match_is_not_account_verification,
    classify_commission_policy,
    classify_observed_commissions,
    commission_per_lot_zero_is_not_explicit_zero,
    cost_adjusted_blocked_when_commission_unknown,
    cost_completeness_from_observed_zero_status,
    cost_completeness_from_unknown_commission,
    cost_completeness_from_verified_schedule_gate_only,
    generic_public_schedule_is_account_specific,
    missing_account_applicability_fields,
    observed_zero_is_not_verified_schedule,
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
from tradingbot.backtest.phase27_12_commission_evidence import PHASE2712_JSON
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON

PHASE2719_JSON = "logs/phase27_19_commission_closure.json"
PHASE2719_MD = "docs_v2/01_truth/PHASE27_19_COMMISSION_CLOSURE.md"
PHASE2717_JSON = "logs/phase27_17_real_broker_evidence.json"

# Public pages inspected this phase. Supporting only. Not account-specific.
PUBLIC_SUPPORTING_DOCS = (
    {
        "url": "https://www.litefinance.org/trading/account-types/ecn/",
        "publisher": "LiteFinance",
        "role": "supporting_only",
        "account_product_claimed": "ECN",
        "claimed_precious_metals_rate_usd_per_lot": 5.0,
        "claimed_basis": "per_lot charged at MT5 open",
        "applies_to_this_account": False,
        "reason_not_verified": "account_product_type UNKNOWN; generic ECN page is not this account's schedule",
    },
    {
        "url": "https://www.litefinance.org/uploads/documents/pdf-litefinance/litefinance-markups-and-commissions-list-en.pdf",
        "publisher": "LiteFinance Global LLC",
        "role": "supporting_only",
        "account_product_claimed": "ECN vs CLASSIC/CENT",
        "claimed_xauusd_ecn_commission": 5.0,
        "claimed_classic_cent_markup_points": 14,
        "effective_date_or_version": "2026-03-26 (document states conditions in force from this date)",
        "applies_to_this_account": False,
        "reason_not_verified": "document is a generic product grid; account product/tier not proven",
    },
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


def public_ecn_supporting_schedule() -> CommissionSchedule:
    return CommissionSchedule(
        broker="LiteFinance Global LLC",
        source=PUBLIC_SUPPORTING_DOCS[0]["url"],
        source_class="GENERIC_PUBLIC",
        public_supporting_only=True,
        asset_class="gold",
        symbol="XAUUSD",
        basis="per_lot",
        currency="USD",
        rate=5.0,
        note="Public ECN precious-metals $5/lot. Supporting only.",
    )


def try_accept(schedule: CommissionSchedule | dict[str, Any], *, account_gate: bool) -> dict[str, Any]:
    fn = accept_account_applicable_schedule if account_gate else accept_verified_schedule
    try:
        accepted = fn(schedule)
        return {"accepted": True, "error": None, "source_class": accepted.source_class}
    except CommissionPolicyError as exc:
        return {"accepted": False, "error": exc.code, "message": exc.message}


def inspect_phase27_12(root: Path) -> dict[str, Any]:
    data = _safe_load_json(root / PHASE2712_JSON) or {}
    tape = data.get("operator_deal_tape") if isinstance(data.get("operator_deal_tape"), dict) else {}
    sched = data.get("verified_schedule") if isinstance(data.get("verified_schedule"), dict) else {}
    ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
    return {
        "artifact": PHASE2712_JSON,
        "present": (root / PHASE2712_JSON).is_file(),
        "phase": data.get("phase"),
        "status": data.get("status"),
        "observed_classification": tape.get("classification"),
        "gold_deal_count": tape.get("gold_deal_count"),
        "observed_zero_count": tape.get("observed_zero_count"),
        "verified_schedule_found": sched.get("found"),
        "verified_schedule_status": sched.get("status"),
        "account_product_type": ctx.get("account_product_type"),
        "basis": ctx.get("basis"),
        "applicability_established": ctx.get("applicability_established"),
    }


def inspect_phase27_17(root: Path) -> dict[str, Any]:
    data = _safe_load_json(root / PHASE2717_JSON) or {}
    comm = data.get("commission_evidence_status") if isinstance(data.get("commission_evidence_status"), dict) else {}
    candidate = comm.get("candidate") if isinstance(comm.get("candidate"), dict) else {}
    acct = data.get("account") if isinstance(data.get("account"), dict) else {}
    return {
        "artifact": PHASE2717_JSON,
        "present": (root / PHASE2717_JSON).is_file(),
        "attach_status": data.get("attach_status"),
        "account_environment": data.get("account_environment") or acct.get("trade_mode_label"),
        "broker": data.get("broker") or acct.get("broker"),
        "server": data.get("server") or acct.get("server"),
        "currency": acct.get("currency"),
        "commission_status": comm.get("status"),
        "verified_schedule_found": comm.get("verified_schedule_found"),
        "verified_schedule_claimed": comm.get("verified_schedule_claimed"),
        "public_documentation_used_as_verified": comm.get("public_documentation_used_as_verified"),
        "missing_applicability_fields": comm.get("missing_applicability_fields"),
        "candidate": candidate,
        "account_product_type": candidate.get("account_product_type") or acct.get("account_product_type") or UNKNOWN,
    }


def build_applicability_matrix(p12: dict[str, Any], p17: dict[str, Any]) -> dict[str, Any]:
    candidate = p17.get("candidate") if isinstance(p17.get("candidate"), dict) else {}
    fields = {
        "broker": p17.get("broker") or "LiteFinance",
        "server": p17.get("server") or UNKNOWN,
        "account_environment": p17.get("account_environment") or UNKNOWN,
        "account_product_type": p17.get("account_product_type") or UNKNOWN,
        "asset_class": candidate.get("asset_class") or "gold",
        "symbol": candidate.get("symbol") or "XAUUSD_i",
        "commission_basis": candidate.get("basis") or UNKNOWN,
        "per_side_vs_round_turn": UNKNOWN,
        "currency": p17.get("currency") or candidate.get("currency") or UNKNOWN,
        "effective_date_or_version": candidate.get("effective_date_or_version") or UNKNOWN,
        "applicability_conditions": [
            "Must match this broker and server",
            "Must match this account environment (Demo vs Real)",
            "Must match this account product / commission tier",
            "Must match gold / XAUUSD_i",
            "Must state per-lot basis and per-side vs round-turn / open-charge rule",
            "Must state commission currency and effective date/version",
        ],
    }
    evidenced = {
        "broker": bool(fields["broker"] and fields["broker"] != UNKNOWN),
        "server": bool(fields["server"] and fields["server"] != UNKNOWN),
        "account_environment": bool(
            fields["account_environment"] and fields["account_environment"] != UNKNOWN
        ),
        "account_product_type": False,
        "asset_class": True,
        "symbol": fields["symbol"] == "XAUUSD_i",
        "commission_basis": False,
        "per_side_vs_round_turn": False,
        "currency": bool(fields["currency"] and fields["currency"] != UNKNOWN),
        "effective_date_or_version": False,
        "applicability_conditions": False,
    }
    # Account currency is evidenced; commission-currency applicability is not.
    return {
        "fields": fields,
        "evidenced": evidenced,
        "applicability_established": False,
        "missing_for_verified": missing_account_applicability_fields(
            {
                "broker": fields["broker"],
                "server": fields["server"],
                "account_type": fields["account_environment"],
                "account_environment": fields["account_environment"],
                "account_product_type": fields["account_product_type"],
                "asset_class": fields["asset_class"],
                "symbol": fields["symbol"],
                "basis": fields["commission_basis"],
                "currency": fields["currency"],
                "effective_date_or_version": fields["effective_date_or_version"],
                "applicability_established": False,
            }
        ),
    }


def contract_self_checks(observed_values: list[float], *, account_broker: str) -> dict[str, Any]:
    generic = public_ecn_supporting_schedule()
    incomplete = CommissionSchedule(
        broker=account_broker,
        server="LiteFinance-MT5-Live",
        account_type="REAL",
        asset_class="gold",
        symbol="XAUUSD_i",
        rate=0.0,
        applicability_established=False,
    )
    name_match_only = CommissionSchedule(
        broker=account_broker,
        source="public_generic_schedule",
        source_class="GENERIC_PUBLIC",
        public_supporting_only=True,
        rate=5.0,
    )
    complete = CommissionSchedule(
        broker=account_broker,
        server="LiteFinance-MT5-Live",
        account_type="REAL",
        account_environment="REAL",
        account_product_type="ECN",
        asset_class="gold",
        symbol="XAUUSD_i",
        basis="per_lot",
        currency="USD",
        effective_date_or_version="fixture-only-not-this-account",
        rate=5.0,
        applicability_established=True,
        source="account_conditions_export",
    )
    cfg = BacktestConfig()
    model_default = build_backtest_cost_model(cfg)
    return {
        "observed_zero_not_verified_schedule": observed_zero_is_not_verified_schedule(observed_values),
        "generic_public_not_account_specific": not generic_public_schedule_is_account_specific(generic),
        "broker_name_match_not_verification": broker_name_match_is_not_account_verification(
            name_match_only, account_broker
        ),
        "generic_not_accepted": not try_accept(generic, account_gate=True)["accepted"],
        "incomplete_not_accepted": not try_accept(incomplete, account_gate=True)["accepted"],
        "name_match_not_accepted": not try_accept(name_match_only, account_gate=True)["accepted"],
        "complete_applicability_can_be_accepted": try_accept(complete, account_gate=True)["accepted"],
        "commission_per_lot_zero_not_explicit_zero": commission_per_lot_zero_is_not_explicit_zero(
            cfg.commission_per_lot, cfg.commission_status
        ),
        "default_commission_status": cfg.commission_status,
        "default_commission_per_lot": cfg.commission_per_lot,
        "default_availability_not_zero": model_default.commission.availability != CostAvailability.ZERO,
        "default_availability_unknown": model_default.commission.availability == CostAvailability.UNKNOWN,
        "completeness_from_unknown": cost_completeness_from_unknown_commission().value,
        "completeness_from_observed_zero": cost_completeness_from_observed_zero_status().value,
        "completeness_from_policy_gate_only": cost_completeness_from_verified_schedule_gate_only().value,
        "assess_default_not_complete": assess_cost_completeness(model_default) != CostCompleteness.COMPLETE,
        "cost_adjusted_blocked": cost_adjusted_blocked_when_commission_unknown(),
    }


def run_phase27_19_commission_closure(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    p12 = inspect_phase27_12(root)
    p17 = inspect_phase27_17(root)
    gold_deals = load_all_gold_deal_records(root)
    values = []
    for deal in gold_deals:
        raw = deal.get("commission")
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    observed = classify_observed_commissions(values)
    matrix = build_applicability_matrix(p12, p17)
    account_broker = str(p17.get("broker") or "LiteFinance Global LLC")
    checks = contract_self_checks(values, account_broker=account_broker)
    generic = public_ecn_supporting_schedule()
    generic_attempt = try_accept(generic, account_gate=True)
    candidate = dict(p17.get("candidate") or {})
    candidate_attempt = try_accept(candidate, account_gate=True) if candidate else {
        "accepted": False,
        "error": "NO_CANDIDATE",
        "message": "No Phase 27.17 candidate schedule",
    }
    classification = classify_commission_policy(
        commission_status=POLICY,
        observed_values=values,
        schedule=None,
    )
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or UNKNOWN
    verified_found = False
    commission_status = UNKNOWN
    commission_blocker = BLOCKED

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.19",
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
        "phase27_12": p12,
        "phase27_17": p17,
        "applicability_matrix": matrix,
        "operator_deal_tape": {
            "gold_deal_count": len(gold_deals),
            "commission_sample_count": observed.sample_count,
            "observed_zero_count": observed.observed_zero_count,
            "observed_nonzero_count": observed.observed_nonzero_count,
            "classification": observed.status,
            "proves_verified_schedule": False,
            "proves_universal_zero": False,
            "note": observed.note,
        },
        "public_supporting_documentation": {
            "used_as_verified": False,
            "used_as_account_specific": False,
            "broker_name_match_used_as_verification": False,
            "documents": list(PUBLIC_SUPPORTING_DOCS),
            "generic_accept_attempt": generic_attempt,
        },
        "verified_schedule": {
            "found": verified_found,
            "accepted": False,
            "status": commission_blocker,
            "commission_status": commission_status,
            "commission_status_display": f"{commission_status} / {commission_blocker}",
            "provenance": None,
            "applicability_established": False,
            "public_documentation_used_as_verified": False,
            "candidate_accept_attempt": candidate_attempt,
            "rate": None,
            "basis": UNKNOWN,
            "currency": UNKNOWN,
            "effective_date_or_version": UNKNOWN,
            "account_product_type": matrix["fields"]["account_product_type"],
        },
        "classification": classification,
        "contract_self_checks": checks,
        "default_commission_status": BacktestConfig().commission_status,
        "default_commission_per_lot": BacktestConfig().commission_per_lot,
        "zero_commission_assumption_enabled": False,
        "phase27_16_final_gate_unchanged": final_gate,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "mt5_restarted": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "strategy_modified": False,
            "commission_fabricated": False,
            "zero_commission_assumed": False,
            "observed_zero_converted_to_verified": False,
            "commission_per_lot_zero_converted_to_zero_status": False,
            "public_schedule_treated_as_account_specific": False,
            "phase_27_20_started": False,
        },
        "deferred": ["Phase 27.20+ — not started"],
    }

    required = (
        p12.get("present"),
        observed.status == OBSERVED_ZERO_NOT_PROVEN,
        observed.sample_count == 50,
        observed.observed_zero_count == 50,
        checks["observed_zero_not_verified_schedule"],
        checks["generic_public_not_account_specific"],
        checks["broker_name_match_not_verification"],
        checks["generic_not_accepted"],
        checks["incomplete_not_accepted"],
        checks["name_match_not_accepted"],
        checks["complete_applicability_can_be_accepted"],
        checks["commission_per_lot_zero_not_explicit_zero"],
        checks["default_commission_status"] == UNKNOWN,
        checks["default_availability_not_zero"],
        checks["completeness_from_unknown"] != CostCompleteness.COMPLETE.value,
        checks["completeness_from_observed_zero"] != CostCompleteness.COMPLETE.value,
        checks["completeness_from_policy_gate_only"] != CostCompleteness.COMPLETE.value,
        checks["cost_adjusted_blocked"],
        not payload["verified_schedule"]["found"],
        payload["verified_schedule"]["commission_status"] in (UNKNOWN, BLOCKED),
        not payload["zero_commission_assumption_enabled"],
        not generic_attempt["accepted"],
        not candidate_attempt["accepted"],
        not matrix["applicability_established"],
        final_gate == "BLOCKED",
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2719_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_known_unknowns(root, payload)
    return payload


def run_phase27_19_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_19_commission_closure(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    tape = payload["operator_deal_tape"]
    matrix = payload["applicability_matrix"]
    fields = matrix["fields"]
    evidenced = matrix["evidenced"]
    sched = payload["verified_schedule"]
    checks = payload["contract_self_checks"]
    p17 = payload["phase27_17"]
    md = f"""# Phase 27.19 — Account-Applicable Commission Schedule Closure

**Status:** {payload['status']}  
**Commission status:** `{sched['commission_status_display']}`  
**Artifact:** `{PHASE2719_JSON}`

## Operator decision

**VERIFIED_SCHEDULE.** Commission may only be accepted for validation when a verified, account-applicable schedule is obtained. Selecting the policy is a **gate**, not current verification.

Observed commission = 0 does **not** prove zero commission. The existing 50 gold deals remain **`OBSERVED_ZERO_NOT_PROVEN`**.

## Prior evidence inspected

| Source | Result |
|---|---|
| Phase 27.12 | `{payload['phase27_12'].get('observed_classification')}`; verified found `{payload['phase27_12'].get('verified_schedule_found')}` |
| Phase 27.17 Real | attach `{p17.get('attach_status')}`; broker `{p17.get('broker')}`; server `{p17.get('server')}`; environment `{p17.get('account_environment')}`; verified claimed `{p17.get('verified_schedule_claimed')}` |

## Applicability matrix

| Field | Evidenced value | Defensible for VERIFIED? |
|---|---|---|
| broker | `{fields['broker']}` | `{evidenced['broker']}` (context only) |
| server | `{fields['server']}` | `{evidenced['server']}` (context only) |
| account environment | `{fields['account_environment']}` | `{evidenced['account_environment']}` (environment, not product) |
| account / product type | `{fields['account_product_type']}` | **False — required, missing** |
| asset class | `{fields['asset_class']}` | supporting only |
| symbol | `{fields['symbol']}` | supporting only |
| commission basis | `{fields['commission_basis']}` | **False — required, missing** |
| per-side vs round-turn | `{fields['per_side_vs_round_turn']}` | **False — required, missing** |
| currency | `{fields['currency']}` | account currency, not proven commission currency |
| effective date / version | `{fields['effective_date_or_version']}` | **False — required, missing** |

Missing for VERIFIED: `{', '.join(matrix['missing_for_verified'])}`.

## Public documentation (supporting only)

Official LiteFinance ECN page lists precious-metals commission **$5 per lot** on MT5, charged at open. The public markups PDF distinguishes ECN commission vs CLASSIC/CENT markup and states conditions in force from 2026-03-26.

These pages were **not** treated as this account's schedule. A broker-name match is not account-specific verification. Account product type remains **UNKNOWN**, so neither the public ECN $5 grid nor a Classic/Cent “no commission / markup in spread” reading can be applied.

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

`BacktestConfig.commission_per_lot={payload['default_commission_per_lot']}` was **not** converted to `CostAvailability.ZERO`.

## Verified schedule

| Field | Value |
|---|---|
| found | **False** |
| accepted | **False** |
| status | **`{sched['commission_status_display']}`** |
| provenance | none |
| applicability established | **False** |
| public docs used as verified | **False** |

## Semantics

| Claim | Result |
|---|---|
| Observed zero ≠ verified schedule | **True** |
| Generic public schedule ≠ account-specific schedule | **True** |
| Broker-name match ≠ verification | **True** |
| Missing applicability ≠ VERIFIED | **True** |
| Complete applicability can be accepted | **True** (fixture only; not this account) |
| UNKNOWN / OBSERVED_ZERO / policy-gate-only block COMPLETE | **True** (`{checks['completeness_from_unknown']}` / `{checks['completeness_from_observed_zero']}` / `{checks['completeness_from_policy_gate_only']}`) |
| Cost-adjusted validation | **BLOCKED** |
| FINAL_GATE | `{payload['phase27_16_final_gate_unchanged']}` |

Default `BacktestConfig.commission_status` remains `{payload['default_commission_status']}` (fail-closed).

## Production

**BLOCKED.** No Strategy, RiskGate, or execution changes. No MT5. No fabricated commission. Phase 27.20+ not started.

## Next

STOP after Phase 27.19.
"""
    (root / PHASE2719_MD).write_text(md, encoding="utf-8")


def _update_known_unknowns(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.19 commission closure:** `{PHASE2719_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.18 historical bid/ask:** `logs/phase27_18_historical_bidask.json`",
            "**Phase 27.18 historical bid/ask:** `logs/phase27_18_historical_bidask.json`  \n" + pointer,
        )
    old = (
        "| Commission universal zero | **UNKNOWN / BLOCKED**. Policy Decision 3 = `VERIFIED_SCHEDULE` (gate). "
        "Phase 27.12: 50 gold deals at 0.0 classified `OBSERVED_ZERO_NOT_PROVEN`; "
        "no account-applicable schedule; observed zero ≠ verified zero |"
    )
    new = (
        "| Commission universal zero | **UNKNOWN / BLOCKED**. Policy Decision 3 = `VERIFIED_SCHEDULE` (gate). "
        "Phase 27.19: 50 gold deals remain `OBSERVED_ZERO_NOT_PROVEN`; public LiteFinance ECN/Classic "
        "pages are supporting only; account/product type UNKNOWN; applicability not established; "
        "observed zero ≠ verified schedule |"
    )
    if old in text:
        text = text.replace(old, new)
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
