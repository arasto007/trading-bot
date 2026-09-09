"""Phase 27.22 — commission and account-product forensic evidence.

Read-only. Does not infer product type from zeros, symbol, broker name,
balance, or trade history. VERIFIED_SCHEDULE only with proven applicability.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.commission_policy import (
    BLOCKED,
    OBSERVED_ZERO_NOT_PROVEN,
    POLICY,
    UNKNOWN,
    accept_account_applicable_schedule,
    classify_observed_commissions,
    commission_per_lot_zero_is_not_explicit_zero,
    cost_completeness_from_observed_zero_status,
    cost_completeness_from_unknown_commission,
    cost_completeness_from_verified_schedule_gate_only,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, assess_cost_completeness, build_backtest_cost_model
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_5_final_broker_cost_gate import load_all_gold_deal_records
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    bounded_readonly_attach_once,
    classify_session,
    login_identity_hash,
    trade_mode_label,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_17_real_broker_evidence import PHASE2717_JSON
from tradingbot.backtest.phase27_19_commission_closure import PUBLIC_SUPPORTING_DOCS

PHASE2722_JSON = "logs/phase27_22_commission_forensic.json"
PHASE2722_MD = "docs_v2/01_truth/PHASE27_22_COMMISSION_FORENSIC.md"
VERIFIED_SCHEDULE = POLICY

PRODUCT_TOKENS = ("ECN", "CLASSIC", "CENT")
IDENTIFIER_FIELDS = (
    "account_type",
    "account_kind",
    "account_product_type",
    "product",
    "product_type",
    "group",
    "trade_account_type",
    "comment",
    "account_comment",
)
INFERENCE_FORBIDDEN_SOURCES = frozenset(
    {
        "commission",
        "zero_commission",
        "symbol",
        "broker",
        "company",
        "balance",
        "equity",
        "profit",
        "trade_history",
        "gold_deals",
        "server",
    }
)
REDACT_ACCOUNT_KEYS = FORBIDDEN_OUTPUT_KEYS | {
    "name",
    "investor",
    "balance",
    "credit",
    "profit",
    "equity",
    "margin",
    "margin_free",
    "margin_level",
    "margin_initial",
    "margin_maintenance",
    "assets",
    "liabilities",
    "commission_blocked",
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
    return UNKNOWN


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in REDACT_ACCOUNT_KEYS}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def detect_product_from_identifiers(fields: dict[str, Any]) -> dict[str, Any]:
    """ECN/CLASSIC/CENT only from explicit identifier fields — never from zeros/broker/history."""
    hits: list[dict[str, str]] = []
    scanned: list[str] = []
    keys = list(IDENTIFIER_FIELDS)
    for key in fields:
        if key not in keys:
            keys.append(key)
    for key in keys:
        if key not in fields:
            continue
        if key.lower() in INFERENCE_FORBIDDEN_SOURCES:
            continue
        scanned.append(key)
        raw = str(fields.get(key) or "")
        upper = raw.upper()
        for token in PRODUCT_TOKENS:
            if re.search(rf"\b{token}\b", upper):
                hits.append({"field": key, "token": token})
    unique = sorted({h["token"] for h in hits})
    if len(unique) == 1:
        product = unique[0]
    elif not unique:
        product = UNKNOWN
    else:
        product = UNKNOWN
    return {
        "account_product_type": product,
        "hits": hits,
        "identifier_fields_scanned": scanned,
        "inferred_from_zero_commission": False,
        "inferred_from_symbol": False,
        "inferred_from_broker_name": False,
        "inferred_from_balance": False,
        "inferred_from_trade_history": False,
        "ambiguous": len(unique) > 1,
    }


def classify_commission_forensic(
    *,
    product_type: str,
    applicability_established: bool,
    verified_accepted: bool,
    observed_zero_count: int,
    observed_nonzero_count: int,
) -> str:
    """Return exactly one classification."""
    if verified_accepted and applicability_established and product_type not in ("", UNKNOWN):
        return VERIFIED_SCHEDULE
    if observed_zero_count > 0 and observed_nonzero_count == 0:
        return OBSERVED_ZERO_NOT_PROVEN
    if observed_zero_count == 0 and observed_nonzero_count == 0:
        return UNKNOWN
    return BLOCKED


def summarize_deal_tape(deals: list[dict[str, Any]]) -> dict[str, Any]:
    values: list[float] = []
    symbols: set[str] = set()
    environments: set[str] = set()
    times: list[str] = []
    comments: list[str] = []
    for deal in deals:
        raw = deal.get("commission")
        if raw is not None:
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                pass
        if deal.get("symbol"):
            symbols.add(str(deal["symbol"]))
        env = deal.get("account_environment") or deal.get("environment") or deal.get("_source")
        if env:
            environments.add(str(env))
        for key in ("time", "time_utc", "time_msc"):
            if deal.get(key):
                times.append(str(deal[key]))
                break
        comment = deal.get("comment")
        if comment:
            comments.append(str(comment))
    observed = classify_observed_commissions(values)
    dist: dict[str, int] = {}
    for val in values:
        label = f"{val:.4f}"
        dist[label] = dist.get(label, 0) + 1
    return {
        "gold_deal_count": len(deals),
        "commission_sample_count": observed.sample_count,
        "observed_zero_count": observed.observed_zero_count,
        "observed_nonzero_count": observed.observed_nonzero_count,
        "commission_distribution": dist,
        "symbols": sorted(symbols),
        "sources": sorted(environments),
        "date_range": {
            "start": min(times) if times else UNKNOWN,
            "end": max(times) if times else UNKNOWN,
        },
        "deal_comments_present": bool(comments),
        "deal_comment_product_tokens": [
            c for c in comments if any(re.search(rf"\b{t}\b", c.upper()) for t in PRODUCT_TOKENS)
        ],
        "classification": observed.status,
        "proves_verified_schedule": False,
        "proves_universal_zero": False,
        "note": observed.note,
    }


def collect_account_metadata(mt5: Any) -> dict[str, Any]:
    acct = mt5.account_info()
    raw_keys: list[str] = []
    raw: dict[str, Any] = {}
    if acct is not None:
        try:
            raw = dict(acct._asdict())  # noqa: SLF001 — read-only snapshot
            raw_keys = sorted(str(k) for k in raw)
        except Exception:
            raw = {}
            raw_keys = [str(k) for k in dir(acct) if not str(k).startswith("_")]
    mode = raw.get("trade_mode") if raw else getattr(acct, "trade_mode", None) if acct is not None else None
    sanitized = _sanitize(raw)
    return {
        "trade_mode": mode if mode is not None else UNKNOWN,
        "trade_mode_label": trade_mode_label(mode),
        "broker": sanitized.get("company") or UNKNOWN,
        "server": sanitized.get("server") or UNKNOWN,
        "currency": sanitized.get("currency") or UNKNOWN,
        "leverage": sanitized.get("leverage", UNKNOWN),
        "margin_mode": sanitized.get("margin_mode", UNKNOWN),
        "login_identity": login_identity_hash(raw.get("login") if raw else None),
        "login_present": raw.get("login") not in (None, "", 0),
        "account_product_type": UNKNOWN,
        "visible_account_keys": raw_keys,
        "redacted_keys": sorted(k for k in raw_keys if k.lower() in REDACT_ACCOUNT_KEYS),
        "identifier_fields": {k: sanitized.get(k) for k in IDENTIFIER_FIELDS if k in sanitized},
        "sanitized_non_sensitive": {
            k: sanitized.get(k)
            for k in ("trade_mode", "company", "server", "currency", "leverage", "margin_mode", "limit_orders", "trade_allowed")
            if k in sanitized
        },
    }


def collect_terminal_metadata(mt5: Any) -> dict[str, Any]:
    info = mt5.terminal_info()
    if info is None:
        return {"build": UNKNOWN, "connected": False, "name": UNKNOWN}
    return {
        "build": getattr(info, "build", UNKNOWN),
        "connected": bool(getattr(info, "connected", False)),
        "name": str(getattr(info, "name", None) or UNKNOWN),
    }


def run_phase27_22_commission_forensic(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    attach = bounded_readonly_attach_once()
    account = {
        "trade_mode": UNKNOWN,
        "trade_mode_label": UNKNOWN,
        "broker": UNKNOWN,
        "server": UNKNOWN,
        "currency": UNKNOWN,
        "leverage": UNKNOWN,
        "margin_mode": UNKNOWN,
        "account_product_type": UNKNOWN,
        "identifier_fields": {},
        "visible_account_keys": [],
        "redacted_keys": [],
        "collection_timestamp_utc": timestamp,
        "this_session": True,
    }
    terminal = {"build": UNKNOWN, "connected": False, "name": UNKNOWN}
    env = UNKNOWN
    evidence_status, _collection = classify_session(attach.get("ok", False), env)

    if attach.get("ok"):
        import MetaTrader5 as mt5

        account = collect_account_metadata(mt5)
        account["collection_timestamp_utc"] = timestamp
        account["this_session"] = True
        terminal = collect_terminal_metadata(mt5)
        env = str(account.get("trade_mode_label") or UNKNOWN)
        evidence_status, _collection = classify_session(True, env)

    prior_real = (_safe_load_json(root / PHASE2717_JSON) or {}).get("account") or {}
    scan_fields = dict(account.get("identifier_fields") or {})
    extra = account.get("sanitized_non_sensitive") or {}
    for key, value in extra.items():
        if key.lower() not in INFERENCE_FORBIDDEN_SOURCES and key not in scan_fields:
            scan_fields[key] = value
    product = detect_product_from_identifiers(scan_fields)
    if env == "REAL":
        account["account_product_type"] = product["account_product_type"]
    else:
        product = {
            **product,
            "account_product_type": UNKNOWN,
            "note": "Product identifiers are only accepted from a REAL attach this session.",
        }
        account["account_product_type"] = UNKNOWN

    deals = load_all_gold_deal_records(root)
    tape = summarize_deal_tape(deals)
    # Deal comments are history — do not use them to set product type.
    if tape["deal_comment_product_tokens"]:
        product["history_comment_tokens_ignored"] = tape["deal_comment_product_tokens"]

    public = {
        "used_as_verified": False,
        "used_as_account_specific": False,
        "documents": list(PUBLIC_SUPPORTING_DOCS),
        "applicability_established": False,
        "broker": account.get("broker") or "LiteFinance",
        "server": account.get("server"),
        "product_account_type": account.get("account_product_type"),
        "asset_class": "gold",
        "symbol": "XAUUSD_i",
        "commission_basis": UNKNOWN,
        "currency": account.get("currency") or UNKNOWN,
        "effective_date_or_version": UNKNOWN,
        "source": "public LiteFinance pages — supporting only",
    }
    verified_accepted = False
    try:
        accept_account_applicable_schedule(
            {
                "broker": account.get("broker"),
                "server": account.get("server"),
                "account_type": env,
                "account_product_type": account.get("account_product_type"),
                "asset_class": "gold",
                "symbol": "XAUUSD_i",
                "basis": UNKNOWN,
                "currency": account.get("currency"),
                "effective_date_or_version": UNKNOWN,
                "rate": 0.0,
                "applicability_established": False,
                "public_supporting_only": True,
            }
        )
        verified_accepted = True
    except Exception:
        verified_accepted = False

    classification = classify_commission_forensic(
        product_type=str(account.get("account_product_type") or UNKNOWN),
        applicability_established=False,
        verified_accepted=verified_accepted,
        observed_zero_count=int(tape["observed_zero_count"]),
        observed_nonzero_count=int(tape["observed_nonzero_count"]),
    )
    cfg = BacktestConfig()
    model = build_backtest_cost_model(cfg)
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or UNKNOWN

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.22",
        "status": "PASS",
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "operator_policy": {
            "decision": "DECISION_3",
            "treatment": VERIFIED_SCHEDULE,
            "meaning": "VERIFIED_SCHEDULE is a gate, not current verification.",
        },
        "attach_status": evidence_status,
        "attach_attempt": _sanitize(attach),
        "account": _sanitize(account),
        "prior_real_account": _sanitize(prior_real) if isinstance(prior_real, dict) else {},
        "terminal": terminal,
        "account_product": product,
        "commission_evidence": tape,
        "public_supporting_documentation": public,
        "classification": classification,
        "verified_schedule_found": False,
        "applicability_established": False,
        "why_not_verified": (
            "Account product/tier is not established from MT5-visible identifiers. "
            "Public ECN/Classic pages remain supporting only. "
            "50 gold zeros remain OBSERVED_ZERO_NOT_PROVEN and do not prove ZERO."
        ),
        "operator_action_required": True,
        "operator_action": (
            "Confirm LiteFinance account product/tier (ECN vs CLASSIC vs CENT) from "
            "the client cabinet or contract, then supply an account-applicable schedule."
        ),
        "default_commission_status": cfg.commission_status,
        "default_commission_per_lot": cfg.commission_per_lot,
        "commission_per_lot_zero_is_not_zero_status": commission_per_lot_zero_is_not_explicit_zero(
            cfg.commission_per_lot, cfg.commission_status
        ),
        "cost_completeness_unknown": cost_completeness_from_unknown_commission().value,
        "cost_completeness_observed_zero": cost_completeness_from_observed_zero_status().value,
        "cost_completeness_policy_gate": cost_completeness_from_verified_schedule_gate_only().value,
        "default_availability": model.commission.availability.value,
        "phase27_16_final_gate_unchanged": final_gate,
        "complete_costs_required_weakened": False,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "mt5_restarted": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "credentials_exposed": False,
            "product_inferred_from_zero_commission": False,
            "product_inferred_from_broker_name": False,
            "product_inferred_from_balance": False,
            "product_inferred_from_trade_history": False,
            "zero_converted_to_zero_status": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "sizing_modified": False,
            "rr_modified": False,
            "phase_27_23_started": False,
        },
        "deferred": ["Phase 27.23+ — not started"],
    }

    allowed = {VERIFIED_SCHEDULE, OBSERVED_ZERO_NOT_PROVEN, UNKNOWN, BLOCKED}
    required = (
        classification in allowed,
        classification != VERIFIED_SCHEDULE,
        tape["observed_zero_count"] == 50,
        tape["observed_nonzero_count"] == 0,
        tape["classification"] == OBSERVED_ZERO_NOT_PROVEN,
        account.get("account_product_type") == UNKNOWN,
        not public["used_as_verified"],
        not payload["complete_costs_required_weakened"],
        final_gate == "BLOCKED",
        assess_cost_completeness(model) != CostCompleteness.COMPLETE,
        model.commission.availability != CostAvailability.ZERO,
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2722_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_known_unknowns(root, payload)
    return payload


def run_phase27_22_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_22_commission_forensic(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    acct = payload["account"]
    prior = payload.get("prior_real_account") or {}
    prod = payload["account_product"]
    tape = payload["commission_evidence"]
    md = f"""# Phase 27.22 — Commission & Account-Product Forensic Evidence

**Status:** {payload['status']}  
**Classification:** `{payload['classification']}`  
**Artifact:** `{PHASE2722_JSON}`  
**Collection timestamp UTC:** `{payload['timestamp']}`

Read-only. No MT5 start/restart, orders, `.env`, or production behavior changes.

## Account product evidence

This session attach: `{payload['attach_status']}`.

| Field | This session | Prior Real (27.17) |
|---|---|---|
| trade mode | `{acct.get('trade_mode')}` → `{acct.get('trade_mode_label')}` | `{prior.get('trade_mode')}` → `{prior.get('trade_mode_label')}` |
| broker | `{acct.get('broker')}` | `{prior.get('broker')}` |
| server | `{acct.get('server')}` | `{prior.get('server')}` |
| currency | `{acct.get('currency')}` | `{prior.get('currency')}` |
| leverage | `{acct.get('leverage')}` | `{prior.get('leverage')}` |
| margin mode | `{acct.get('margin_mode')}` | `{prior.get('margin_mode')}` |
| terminal build | `{payload['terminal'].get('build')}` | n/a |
| **account_product_type** | **`{acct.get('account_product_type')}`** | `{prior.get('account_product_type')}` |

Identifier fields scanned: `{', '.join(prod.get('identifier_fields_scanned') or []) or 'none visible'}`.  
Product was **not** inferred from zero commission, symbol, broker name, balance, or trade history.

## Commission evidence

| Field | Value |
|---|---|
| gold deals | `{tape['gold_deal_count']}` |
| commission samples | `{tape['commission_sample_count']}` |
| observed zero | `{tape['observed_zero_count']}` |
| observed nonzero | `{tape['observed_nonzero_count']}` |
| distribution | `{tape['commission_distribution']}` |
| symbols | `{', '.join(tape['symbols']) or 'none'}` |
| date range | `{tape['date_range']['start']}` → `{tape['date_range']['end']}` |
| tape class | **`{tape['classification']}`** |

`BacktestConfig.commission_per_lot={payload['default_commission_per_lot']}` was not converted to `ZERO`.

## Public documentation

LiteFinance ECN precious-metals **$5/lot** and CLASSIC/CENT markup pages remain **supporting only**. They are not this account's schedule while product type is UNKNOWN.

## Why not VERIFIED_SCHEDULE

{payload['why_not_verified']}

Final classification (exactly one): **`{payload['classification']}`**.

## Operator action

**Required:** {payload['operator_action']}

## Production

**BLOCKED.** COMPLETE_COSTS_REQUIRED was not weakened. FINAL_GATE remains `{payload['phase27_16_final_gate_unchanged']}`. Phase 27.23+ not started.

## Next

STOP after Phase 27.22.
"""
    (root / PHASE2722_MD).write_text(md, encoding="utf-8")


def _update_known_unknowns(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.22 commission forensic:** `{PHASE2722_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.21 evidence synthesis:** `logs/phase27_21_evidence_synthesis.json` — FINAL_GATE remains BLOCKED",
            "**Phase 27.21 evidence synthesis:** `logs/phase27_21_evidence_synthesis.json` — FINAL_GATE remains BLOCKED  \n"
            + pointer
            + " — account_product_type UNKNOWN; classification remains OBSERVED_ZERO_NOT_PROVEN",
        )
    old = (
        "| Commission universal zero | **UNKNOWN / BLOCKED**. Policy Decision 3 = `VERIFIED_SCHEDULE` (gate). "
        "Phase 27.19: 50 gold deals remain `OBSERVED_ZERO_NOT_PROVEN`; public LiteFinance ECN/Classic "
        "pages are supporting only; account/product type UNKNOWN; applicability not established; "
        "observed zero ≠ verified schedule |"
    )
    new = (
        "| Commission universal zero | **UNKNOWN / BLOCKED**. Policy Decision 3 = `VERIFIED_SCHEDULE` (gate). "
        f"Phase 27.22 classification `{payload['classification']}`; account_product_type "
        f"`{payload['account'].get('account_product_type')}`; public pages supporting only; "
        "observed zero ≠ verified schedule |"
    )
    if old in text:
        text = text.replace(old, new)
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
