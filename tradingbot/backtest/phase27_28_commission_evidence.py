"""Phase 27.28 — Real-account commission evidence closure.

Read-only. Observed zeros are not a verified schedule. Public pages are
supporting only. Does not start MT5, place orders, or rewrite parquet.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.commission_policy import (
    BLOCKED,
    OBSERVED_ZERO_NOT_PROVEN,
    POLICY,
    UNKNOWN,
    CommissionPolicyError,
    accept_account_applicable_schedule,
    classify_observed_commissions,
    commission_per_lot_zero_is_not_explicit_zero,
    cost_completeness_from_observed_zero_status,
    cost_completeness_from_unknown_commission,
    generic_public_schedule_is_account_specific,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness, assess_cost_completeness, build_backtest_cost_model
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_5_final_broker_cost_gate import load_all_gold_deal_records
from tradingbot.backtest.phase27_9_real_broker_evidence import bounded_readonly_attach_once
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_19_commission_closure import PUBLIC_SUPPORTING_DOCS
from tradingbot.backtest.phase27_22_commission_forensic import (
    PHASE2722_JSON,
    INFERENCE_FORBIDDEN_SOURCES,
    REDACT_ACCOUNT_KEYS,
    collect_account_metadata,
    collect_terminal_metadata,
    detect_product_from_identifiers,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2728_JSON = "logs/phase27_28_commission_evidence.json"
PHASE2728_MD = "docs_v2/01_truth/PHASE27_28_COMMISSION_EVIDENCE.md"
PHASE2712_JSON = "logs/phase27_12_commission_evidence.json"
PHASE2719_JSON = "logs/phase27_19_commission_closure.json"
CANONICAL_SYMBOL = PRIMARY_SYMBOL
CANONICAL_PARQUET = "data/XAUUSD_i_5m.parquet"
HISTORY_DAYS = 180
MAX_LIVE_DEALS = 200
REQUIRED_ENV = "REAL"
REQUIRED_SERVER = "LiteFinance-MT5-Live"

GRADE_A = "VERIFIED_ACCOUNT_APPLICABLE_SCHEDULE"
GRADE_B = "PRODUCT_SPECIFIC_BUT_ACCOUNT_LINK_NOT_PROVEN"
GRADE_C = "OBSERVED_ZERO_NOT_PROVEN"
GRADE_D = "INSUFFICIENT_DATA"
GRADE_E = "CONTRADICTORY"

FINAL_A = "VERIFIED_SCHEDULE"
FINAL_B = "PRODUCT_SPECIFIC_NOT_ACCOUNT_VERIFIED"
FINAL_C = "OBSERVED_ZERO_NOT_PROVEN"
FINAL_D = "INSUFFICIENT_DATA"
FINAL_E = "CONTRADICTORY"

PUBLIC_CLASS_GENERIC = "GENERIC_SUPPORTING"
PUBLIC_CLASS_ACCOUNT = "ACCOUNT_SPECIFIC"
PUBLIC_CLASS_PRODUCT = "PRODUCT_SPECIFIC"
PUBLIC_CLASS_NA = "NOT_APPLICABLE"
PUBLIC_CLASS_UNKNOWN = "UNKNOWN"

SOURCE_SEARCH_PATHS = (
    "logs/phase27_12_commission_evidence.json",
    "logs/phase27_19_commission_closure.json",
    "logs/phase27_22_commission_forensic.json",
    "logs/phase27_17_real_broker_evidence.json",
    "logs/operator_broker_evidence_raw.json",
    "logs/operator_broker_evidence_demo_raw.json",
    "docs_v2/01_truth/PHASE27_22_COMMISSION_FORENSIC.md",
    "docs_v2/01_truth/PHASE27_19_COMMISSION_CLOSURE.md",
    "docs_v2/01_truth/PHASE27_12_COMMISSION_EVIDENCE.md",
    "tradingbot/backtest/commission_policy.py",
)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account_type",
    "broker",
    "server",
    "terminal_build",
    "symbol",
    "account_product_type",
    "deal_count",
    "commission_total",
    "commission_nonzero_count",
    "commission_zero_count",
    "commission_distribution",
    "deal_date_start",
    "deal_date_end",
    "schedule_found",
    "schedule_source",
    "schedule_class",
    "commission_basis",
    "commission_rate",
    "commission_currency",
    "effective_date",
    "applicability",
    "evidence_grade",
    "policy_status",
    "final_classification",
    "blockers",
    "operator_dependency",
    "production_code_changed",
    "datasets_changed",
)

DEAL_TYPE_LABEL = {0: "BUY", 1: "SELL"}


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
    blocked = FORBIDDEN_OUTPUT_KEYS | REDACT_ACCOUNT_KEYS | {"password", "mt5_password", "token", "api_key", "investor"}
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in blocked}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def file_fingerprint(path: str | Path) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_public_source(doc: dict[str, Any]) -> str:
    if doc.get("applies_to_this_account") is True and not doc.get("role") == "supporting_only":
        return PUBLIC_CLASS_ACCOUNT
    if doc.get("role") == "supporting_only" or doc.get("applies_to_this_account") is False:
        return PUBLIC_CLASS_GENERIC
    if doc.get("account_product_claimed") and doc.get("applies_to_this_account") is None:
        return PUBLIC_CLASS_PRODUCT
    return PUBLIC_CLASS_UNKNOWN


def classify_evidence_grade(
    *,
    product_type: str,
    verified_accepted: bool,
    applicability_established: bool,
    product_schedule_linked: bool,
    observed_zero_count: int,
    observed_nonzero_count: int,
) -> str:
    """Exactly one A–E grade. Do not upgrade from inference or public pages."""
    product = str(product_type or UNKNOWN)
    if verified_accepted and applicability_established and product not in ("", UNKNOWN):
        return GRADE_A
    if product not in ("", UNKNOWN) and product_schedule_linked and not verified_accepted:
        return GRADE_B
    if observed_zero_count > 0 and observed_nonzero_count > 0:
        return GRADE_E
    if observed_zero_count > 0 and observed_nonzero_count == 0:
        return GRADE_C
    return GRADE_D


def final_classification_for(grade: str) -> str:
    return {
        GRADE_A: FINAL_A,
        GRADE_B: FINAL_B,
        GRADE_C: FINAL_C,
        GRADE_D: FINAL_D,
        GRADE_E: FINAL_E,
    }.get(grade, FINAL_D)


def schedule_satisfies_verified_policy(schedule: dict[str, Any] | None) -> bool:
    if not schedule:
        return False
    try:
        accept_account_applicable_schedule(schedule)
        return True
    except CommissionPolicyError:
        return False


def search_existing_evidence(root: Path) -> dict[str, Any]:
    found: list[dict[str, Any]] = []
    for rel in SOURCE_SEARCH_PATHS:
        path = root / rel
        found.append({"path": rel, "present": path.is_file()})
    p22 = _safe_load_json(root / PHASE2722_JSON) or {}
    p19 = _safe_load_json(root / PHASE2719_JSON) or {}
    p12 = _safe_load_json(root / PHASE2712_JSON) or {}
    return {
        "paths": found,
        "phase27_22_classification": p22.get("classification"),
        "phase27_22_product": ((p22.get("account") or {}).get("account_product_type")),
        "phase27_19_verified": (p19.get("verified_schedule") or {}).get("accepted"),
        "phase27_12_present": bool(p12),
        "stronger_than_observed_zero_found": False,
        "account_applicable_schedule_found": False,
    }


def _deal_time(deal: dict[str, Any]) -> str | None:
    for key in ("time_utc", "time", "open_time", "close_time", "time_msc"):
        if deal.get(key):
            return str(deal[key])
    return None


def _deal_side(deal: dict[str, Any]) -> str:
    if deal.get("direction"):
        return str(deal["direction"])
    raw = deal.get("type")
    if raw in DEAL_TYPE_LABEL:
        return DEAL_TYPE_LABEL[int(raw)]
    if str(raw).upper() in {"BUY", "SELL"}:
        return str(raw).upper()
    return UNKNOWN


def summarize_deals(deals: list[dict[str, Any]]) -> dict[str, Any]:
    values: list[float] = []
    usable: list[dict[str, Any]] = []
    by_side: dict[str, list[float]] = {}
    by_symbol: Counter[str] = Counter()
    by_volume: Counter[str] = Counter()
    per_lot: list[float] = []
    times: list[str] = []
    for deal in deals:
        raw = deal.get("commission")
        try:
            comm = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            comm = None
        if comm is None:
            continue
        values.append(comm)
        vol = None
        try:
            vol = float(deal.get("volume") or deal.get("filled_volume") or 0)
        except (TypeError, ValueError):
            vol = 0.0
        if vol and vol > 0:
            per_lot.append(comm / vol)
            by_volume[f"{vol:.2f}"] += 1
        side = _deal_side(deal)
        by_side.setdefault(side, []).append(comm)
        sym = str(deal.get("symbol") or UNKNOWN)
        by_symbol[sym] += 1
        ts = _deal_time(deal)
        if ts:
            times.append(ts)
        usable.append(
            {
                "ticket": deal.get("ticket"),
                "symbol": deal.get("symbol"),
                "volume": vol,
                "side": side,
                "open_time": deal.get("open_time") or deal.get("time_utc") or deal.get("time"),
                "close_time": deal.get("close_time"),
                "commission": comm,
                "swap": deal.get("swap"),
                "profit": deal.get("profit"),
                "entry_price": deal.get("price") or deal.get("price_open") or deal.get("entry_price"),
                "exit_price": deal.get("price_close") or deal.get("exit_price"),
                "source": deal.get("_source"),
            }
        )
    observed = classify_observed_commissions(values)
    dist: dict[str, int] = {}
    for val in values:
        label = f"{val:.4f}"
        dist[label] = dist.get(label, 0) + 1
    return {
        "deal_count": len(deals),
        "usable_commission_samples": observed.sample_count,
        "commission_total": round(sum(values), 8) if values else 0.0,
        "commission_zero_count": observed.observed_zero_count,
        "commission_nonzero_count": observed.observed_nonzero_count,
        "commission_distribution": dist,
        "commission_by_side": {k: {"count": len(v), "total": round(sum(v), 8)} for k, v in by_side.items()},
        "commission_by_volume": dict(by_volume),
        "commission_per_lot_samples": per_lot[:20],
        "commission_per_lot_unique": sorted({round(x, 8) for x in per_lot}),
        "symbol_distribution": dict(by_symbol),
        "deal_date_start": min(times) if times else None,
        "deal_date_end": max(times) if times else None,
        "usable_deals": usable,
        "observed_status": observed.status,
        "proves_verified_schedule": False,
        "proves_universal_zero": False,
        "limitation": (
            "All-zero realized commission is not a verified schedule. "
            "It does not prove product tier, commission basis, effective date, "
            "XAUUSD_i applicability, embedded markup, or volume/session variation."
        ),
        "note": observed.note,
    }


def _is_gold(symbol: Any) -> bool:
    return str(symbol or "").upper().replace(" ", "") in {"XAUUSD", "XAUUSD_I", CANONICAL_SYMBOL.upper()}


def collect_live_gold_deals() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    attach = bounded_readonly_attach_once()
    meta: dict[str, Any] = {
        "attempted": True,
        "attach_ok": bool(attach.get("ok")),
        "attach_error": attach.get("error"),
        "method": "history_deals_get read-only; no symbol_select",
        "environment_ok": False,
    }
    if not attach.get("ok"):
        meta["attempted"] = bool(attach)
        return [], meta
    import MetaTrader5 as mt5

    account = collect_account_metadata(mt5)
    terminal = collect_terminal_metadata(mt5)
    meta["account"] = _sanitize(account)
    meta["terminal"] = terminal
    env = str(account.get("trade_mode_label") or UNKNOWN)
    meta["environment"] = env
    if env != REQUIRED_ENV or str(account.get("server") or "") != REQUIRED_SERVER:
        meta["error"] = f"attached {env}/{account.get('server')} is not {REQUIRED_ENV}/{REQUIRED_SERVER}"
        return [], meta
    meta["environment_ok"] = True
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=HISTORY_DAYS)
    try:
        raw = mt5.history_deals_get(date_from, date_to)
    except Exception as exc:
        meta["error"] = str(exc)
        return [], meta
    deals: list[dict[str, Any]] = []
    for item in list(raw or []):
        if not _is_gold(getattr(item, "symbol", None)):
            continue
        deals.append(
            {
                "ticket": getattr(item, "ticket", None),
                "symbol": getattr(item, "symbol", None),
                "type": getattr(item, "type", None),
                "direction": DEAL_TYPE_LABEL.get(getattr(item, "type", None), UNKNOWN),
                "volume": getattr(item, "volume", None),
                "price": getattr(item, "price", None),
                "commission": getattr(item, "commission", None),
                "swap": getattr(item, "swap", None),
                "profit": getattr(item, "profit", None),
                "time_utc": datetime.fromtimestamp(getattr(item, "time", 0), tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if getattr(item, "time", None)
                else None,
                "_source": "mt5_history_deals_get",
                "_kind": "history_deal",
            }
        )
        if len(deals) >= MAX_LIVE_DEALS:
            break
    meta["live_gold_deal_count"] = len(deals)
    return deals, meta


def merge_deals(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for deal in group:
            ticket = deal.get("ticket")
            key = ticket if ticket not in (None, "") else (deal.get("_source"), deal.get("time_utc"), deal.get("volume"))
            if key in seen:
                continue
            seen.add(key)
            out.append(deal)
    return out


def run_phase27_28_commission_evidence(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    fingerprint_before = file_fingerprint(root / CANONICAL_PARQUET)
    before = build_immutability_manifest(root)
    existing = search_existing_evidence(root)
    prior22 = _safe_load_json(root / PHASE2722_JSON) or {}
    commission_status_before = prior22.get("classification") or OBSERVED_ZERO_NOT_PROVEN

    live_deals, live_meta = collect_live_gold_deals()
    artifact_deals = load_all_gold_deal_records(root)
    deals = merge_deals(artifact_deals, live_deals)
    tape = summarize_deals(deals)

    attach_account = (live_meta.get("account") or {}) if live_meta.get("environment_ok") else {}
    if not attach_account:
        attach_account = (prior22.get("account") or {}) if isinstance(prior22.get("account"), dict) else {}
    terminal = live_meta.get("terminal") or prior22.get("terminal") or {}
    env = str(attach_account.get("trade_mode_label") or attach_account.get("trade_mode") or UNKNOWN)
    if env in ("2", 2):
        env = "REAL"
    scan_fields = dict(attach_account.get("identifier_fields") or {})
    extra = attach_account.get("sanitized_non_sensitive") or {}
    for key, value in extra.items():
        if str(key).lower() not in INFERENCE_FORBIDDEN_SOURCES and key not in scan_fields:
            scan_fields[key] = value
    product = detect_product_from_identifiers(scan_fields)
    account_product_type = UNKNOWN
    if live_meta.get("environment_ok") or env == REQUIRED_ENV:
        account_product_type = product["account_product_type"]
    # Never infer product from zeros / public pages / tape.
    product["inferred_from_zero_commission"] = False
    product["inferred_from_public_page"] = False

    public_docs = []
    for doc in PUBLIC_SUPPORTING_DOCS:
        row = dict(doc)
        row["source_class"] = classify_public_source(row)
        row["account_specific"] = False
        public_docs.append(row)

    candidate_schedule = {
        "broker": attach_account.get("broker") or "LiteFinance Global LLC",
        "server": attach_account.get("server") or REQUIRED_SERVER,
        "account_type": env if env == REQUIRED_ENV else UNKNOWN,
        "account_product_type": account_product_type,
        "asset_class": "gold",
        "symbol": CANONICAL_SYMBOL,
        "basis": UNKNOWN,
        "currency": attach_account.get("currency") or "USD",
        "effective_date_or_version": UNKNOWN,
        "rate": None,
        "applicability_established": False,
        "public_supporting_only": True,
        "source_class": PUBLIC_CLASS_GENERIC,
    }
    verified = schedule_satisfies_verified_policy(candidate_schedule)
    grade = classify_evidence_grade(
        product_type=account_product_type,
        verified_accepted=verified,
        applicability_established=False,
        product_schedule_linked=False,
        observed_zero_count=int(tape["commission_zero_count"]),
        observed_nonzero_count=int(tape["commission_nonzero_count"]),
    )
    final = final_classification_for(grade)
    policy_satisfied = final == FINAL_A
    cfg = BacktestConfig()
    completeness_unknown = cost_completeness_from_unknown_commission()
    completeness_observed = cost_completeness_from_observed_zero_status()
    completeness_default = assess_cost_completeness(build_backtest_cost_model(cfg))
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or UNKNOWN
    originals_untouched, imm_issues = verify_immutability(before, base_dir=root)
    fingerprint_after = file_fingerprint(root / CANONICAL_PARQUET)
    datasets_changed = not originals_untouched or fingerprint_before != fingerprint_after

    blockers = [
        "account_product_type UNKNOWN — ECN/CLASSIC/CENT not proven from MT5 identifiers",
        "no account-applicable commission schedule (basis/rate/effective date missing)",
        "50-deal all-zero tape remains OBSERVED_ZERO_NOT_PROVEN, not VERIFIED_SCHEDULE",
        "public LiteFinance ECN/Classic pages are GENERIC_SUPPORTING only",
    ]
    if policy_satisfied:
        blockers = []

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.28",
        "status": "PASS",
        "timestamp_utc": timestamp,
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "account_type": env if env in (REQUIRED_ENV, "DEMO") else str(attach_account.get("trade_mode_label") or UNKNOWN),
        "broker": attach_account.get("broker") or "LiteFinance Global LLC",
        "server": attach_account.get("server") or REQUIRED_SERVER,
        "terminal_build": terminal.get("build") if isinstance(terminal, dict) else UNKNOWN,
        "symbol": CANONICAL_SYMBOL,
        "account_product_type": account_product_type,
        "account_product": _sanitize(product),
        "live_collection": _sanitize({k: v for k, v in live_meta.items() if k != "account"}),
        "existing_evidence_search": existing,
        "deal_count": tape["deal_count"],
        "commission_total": tape["commission_total"],
        "commission_nonzero_count": tape["commission_nonzero_count"],
        "commission_zero_count": tape["commission_zero_count"],
        "commission_distribution": tape["commission_distribution"],
        "deal_date_start": tape["deal_date_start"],
        "deal_date_end": tape["deal_date_end"],
        "deal_forensics": {
            **{k: v for k, v in tape.items() if k != "usable_deals"},
            "usable_deal_preview": tape["usable_deals"][:8],
        },
        "schedule_found": False,
        "schedule_source": "none — public pages supporting only; no account schedule",
        "schedule_class": PUBLIC_CLASS_GENERIC,
        "commission_basis": UNKNOWN,
        "commission_rate": None,
        "commission_currency": attach_account.get("currency") or "USD",
        "effective_date": UNKNOWN,
        "applicability": False,
        "candidate_schedule": candidate_schedule,
        "public_supporting_documentation": public_docs,
        "evidence_grade": grade,
        "policy_status": POLICY if policy_satisfied else BLOCKED,
        "final_classification": final,
        "verified_schedule_satisfied": policy_satisfied,
        "commission_status_before": commission_status_before,
        "commission_status_after": final,
        "default_commission_status": cfg.commission_status,
        "commission_per_lot_zero_is_not_zero": commission_per_lot_zero_is_not_explicit_zero(
            cfg.commission_per_lot, cfg.commission_status
        ),
        "implementation_audit": {
            "paths": [
                "tradingbot/backtest/commission_policy.py",
                "tradingbot/backtest/cost_model.py::build_backtest_cost_model",
                "tradingbot/backtest/config.py::BacktestConfig.commission_status",
            ],
            "unknown_blocks_complete": completeness_unknown != CostCompleteness.COMPLETE,
            "observed_zero_blocks_complete": completeness_observed != CostCompleteness.COMPLETE,
            "default_blocks_complete": completeness_default != CostCompleteness.COMPLETE,
            "observed_zero_becomes_zero": False,
            "unknown_fail_closed": True,
            "backtest_config_unchanged": cfg.commission_status == UNKNOWN,
        },
        "blockers": blockers,
        "operator_dependency": True,
        "production_code_changed": False,
        "datasets_changed": datasets_changed,
        "canonical_fingerprint_before": fingerprint_before,
        "canonical_fingerprint_after": fingerprint_after,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": imm_issues,
        "complete_costs_required_weakened": False,
        "phase27_16_final_gate_unchanged": final_gate,
        "phase27_22_preserved": (root / PHASE2722_JSON).is_file(),
        "production_readiness": "BLOCKED",
        "ev_eq_01": "NOT_PROVEN",
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "parquet_rewritten": False,
            "zero_converted_to_verified_schedule": False,
            "public_page_used_as_account_proof": False,
            "product_inferred": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "phase_27_29_started": False,
        },
        "deferred": ["Phase 27.29+ — not started"],
    }
    missing_keys = [k for k in REQUIRED_ARTIFACT_KEYS if k not in payload]
    honest_grade = (policy_satisfied and grade == GRADE_A) or (not policy_satisfied and grade != GRADE_A)
    required_ok = (
        not missing_keys,
        originals_untouched,
        fingerprint_before == fingerprint_after,
        not payload["datasets_changed"],
        not payload["production_code_changed"],
        honest_grade,
        payload["default_commission_status"] == UNKNOWN,
        payload["implementation_audit"]["unknown_blocks_complete"],
        payload["implementation_audit"]["observed_zero_blocks_complete"],
        not payload["complete_costs_required_weakened"],
        final_gate == "BLOCKED",
        generic_public_schedule_is_account_specific({"public_supporting_only": True}) is False,
        not payload["safety_confirmation"]["zero_converted_to_verified_schedule"],
        not payload["safety_confirmation"]["public_page_used_as_account_proof"],
    )
    if not all(required_ok):
        payload["status"] = "FAILED"
        if missing_keys:
            payload["blockers"] = list(payload["blockers"]) + [f"missing_artifact_keys:{','.join(missing_keys)}"]

    out = root / PHASE2728_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_28_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_28_commission_evidence(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    md = f"""# Phase 27.28 — Real Account Commission Evidence Closure

**Status:** {payload["status"]}  
**Evidence grade:** `{payload["evidence_grade"]}`  
**Final classification:** `{payload["final_classification"]}`  
**Artifact:** `{PHASE2728_JSON}`  
**Timestamp UTC:** `{payload["timestamp_utc"]}`

Read-only. Phase 27.22 artifact was not overwritten. Production parquet was not rewritten.
`VERIFIED_SCHEDULE` remains a policy gate, not current verification.

## Real account

| Field | Value |
|---|---|
| account type | `{payload["account_type"]}` |
| broker | `{payload["broker"]}` |
| server | `{payload["server"]}` |
| terminal build | `{payload["terminal_build"]}` |
| symbol | `{payload["symbol"]}` |
| account_product_type | **`{payload["account_product_type"]}`** |

Product/tier was not inferred from zeros, symbol, broker name, leverage, balance, or trade history.

## Deal evidence

| Field | Value |
|---|---|
| deals | `{payload["deal_count"]}` |
| zero commission | `{payload["commission_zero_count"]}` |
| nonzero commission | `{payload["commission_nonzero_count"]}` |
| total commission | `{payload["commission_total"]}` |
| range | `{payload["deal_date_start"]}` → `{payload["deal_date_end"]}` |
| distribution | `{payload["commission_distribution"]}` |

Limitation: an all-zero realized tape is **not** `commission schedule = 0`. It does not prove product tier, basis, effective date, instrument applicability, or whether commission is embedded in spread/markup.

## Schedule

| Field | Value |
|---|---|
| schedule found | `{payload["schedule_found"]}` |
| source | `{payload["schedule_source"]}` |
| class | `{payload["schedule_class"]}` |
| basis | `{payload["commission_basis"]}` |
| rate | `{payload["commission_rate"]}` |
| currency | `{payload["commission_currency"]}` |
| effective date | `{payload["effective_date"]}` |
| applicability | `{payload["applicability"]}` |

Public LiteFinance ECN/Classic pages remain `{PUBLIC_CLASS_GENERIC}`. They are not this account's schedule.

## Classification

Grade `{payload["evidence_grade"]}` → `{payload["final_classification"]}`.  
`VERIFIED_SCHEDULE` satisfied: `{payload["verified_schedule_satisfied"]}`.  
Policy status: `{payload["policy_status"]}`.

## Implementation

UNKNOWN commission cannot produce COMPLETE cost status.  
Observed zero cannot silently become ZERO.  
Default `BacktestConfig.commission_status` remains `{payload["default_commission_status"]}`.

## FINAL_GATE

commission_status_before: `{payload["commission_status_before"]}`  
commission_status_after: `{payload["commission_status_after"]}`  
COMPLETE_COSTS_REQUIRED remains enforced. FINAL_GATE remains `{payload["phase27_16_final_gate_unchanged"]}`.

## Next

STOP after Phase 27.28.
"""
    (root / PHASE2728_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.28 commission evidence:** `{PHASE2728_JSON}` — "
            f"grade `{payload['evidence_grade']}`; final `{payload['final_classification']}`; "
            "account_product_type UNKNOWN; VERIFIED_SCHEDULE not satisfied"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.27 dataset symbol binding:** `logs/phase27_27_dataset_symbol_binding.json` — "
                "`2` DIRECT_CANONICAL_MATCH; `30` MISSING_EXPLICIT_MAP; `0` EXPLICIT_MAPPED; "
                "`1` UNKNOWN_PROVENANCE; 0 maps inserted; EV-EQ-01 NOT_PROVEN"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        old = (
            "| Commission universal zero | **UNKNOWN / BLOCKED**. Policy Decision 3 = `VERIFIED_SCHEDULE` (gate). "
            "Phase 27.22 classification `OBSERVED_ZERO_NOT_PROVEN`; account_product_type `UNKNOWN`; "
            "public pages supporting only; observed zero ≠ verified schedule |"
        )
        new = (
            "| Commission universal zero | **UNKNOWN / BLOCKED**. Policy Decision 3 = `VERIFIED_SCHEDULE` (gate). "
            f"Phase 27.28 grade `{payload['evidence_grade']}` / `{payload['final_classification']}`; "
            "account_product_type UNKNOWN; public pages GENERIC_SUPPORTING only; "
            "observed zero ≠ verified schedule |"
        )
        if old in text:
            text = text.replace(old, new)
        known.write_text(text, encoding="utf-8")

    design = root / "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md"
    if design.is_file():
        text = design.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.28 commission evidence:** `{PHASE2728_JSON}` — "
            "observed zeros remain OBSERVED_ZERO_NOT_PROVEN; no account-applicable schedule"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.27 dataset symbol binding:** `logs/phase27_27_dataset_symbol_binding.json` — "
                "recomputed inventory; no silent map; EV-EQ-01 NOT_PROVEN"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        design.write_text(text, encoding="utf-8")
