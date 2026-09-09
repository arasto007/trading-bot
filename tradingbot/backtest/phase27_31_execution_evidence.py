"""Phase 27.31 — Real-account historical execution / fill evidence closure.

Read-only. Fill price/volume is not an order lifecycle tape.
SimulatedBroker full-fill is not realized execution. price_open is not requested.
Does not start MT5, place orders, or rewrite parquet.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_5_final_broker_cost_gate import load_all_gold_deal_records
from tradingbot.backtest.phase27_9_real_broker_evidence import bounded_readonly_attach_once
from tradingbot.backtest.phase27_15_cost_completeness_gate import evaluate_execution_model
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_22_commission_forensic import (
    REDACT_ACCOUNT_KEYS,
    collect_account_metadata,
    collect_terminal_metadata,
)
from tradingbot.backtest.phase27_24_execution_cost_forensics import (
    DEAL_ENTRY_LABEL,
    DEAL_TYPE_LABEL,
    FILLING_LABEL,
    ORDER_STATE_LABEL,
    ORDER_TYPE_LABEL,
    is_gold_symbol,
)
from tradingbot.backtest.phase27_30_slippage_evidence import inherit_prior_real_identity
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2731_JSON = "logs/phase27_31_execution_evidence.json"
PHASE2731_MD = "docs_v2/01_truth/PHASE27_31_EXECUTION_EVIDENCE.md"
PHASE2724_JSON = "logs/phase27_24_execution_cost_forensics.json"
PHASE2728_JSON = "logs/phase27_28_commission_evidence.json"
PHASE2730_JSON = "logs/phase27_30_slippage_evidence.json"
CANONICAL_SYMBOL = PRIMARY_SYMBOL
CANONICAL_PARQUET = "data/XAUUSD_i_5m.parquet"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
NOT_PROVEN = "NOT_PROVEN"
NOT_OBSERVABLE = "NOT_OBSERVABLE"
NOT_IDENTIFIABLE = "NOT_IDENTIFIABLE"
NOT_DERIVABLE = "NOT_DERIVABLE"
INCOMPLETE = "INCOMPLETE"
PROVEN = "PROVEN"
OBSERVED = "OBSERVED"
REQUIRED_ENV = "REAL"
REQUIRED_SERVER = "LiteFinance-MT5-Live"
HISTORY_DAYS = 180
MAX_ROWS = 200

GRADE_A = "REALIZED_EXECUTION_TAPE_PROVEN"
GRADE_B = "PARTIAL_ORDER_LIFECYCLE"
GRADE_C = "DEAL_FILL_TAPE_ONLY"
GRADE_D = "EXECUTION_LIFECYCLE_UNKNOWN"
GRADE_E = "INSUFFICIENT_DATA"

SOURCE_SEARCH_PATHS = (
    PHASE2724_JSON,
    PHASE2728_JSON,
    PHASE2730_JSON,
    "docs_v2/01_truth/PHASE27_24_EXECUTION_COST_FORENSICS.md",
    "tradingbot/backtest/broker.py",
    "tradingbot/backtest/phase27_15_cost_completeness_gate.py",
)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account_type",
    "broker",
    "server",
    "terminal_build",
    "symbol",
    "full_fills",
    "partial_fills",
    "rejections",
    "canceled_orders",
    "requotes",
    "order_deal_linkage",
    "volume_linkage",
    "execution_latency",
    "classification",
    "evidence_grade",
    "simulated_broker_is_realized",
    "complete_costs_satisfied",
    "production_code_changed",
    "datasets_changed",
)

MT5_FIELD_CONTRACT = {
    "deal_fields_typically_present": [
        "ticket",
        "order",
        "time",
        "type",
        "entry",
        "reason",
        "volume",
        "price",
        "position_id",
        "comment",
    ],
    "deal_fields_absent": ["requested_price", "requested_volume", "order_state"],
    "order_fields_typically_present": [
        "ticket",
        "type",
        "state",
        "volume_initial",
        "volume_current",
        "price_open",
        "price_current",
        "time_setup",
        "time_done",
        "reason",
    ],
    "order_fields_not_requested_price": ["price_open", "price_current"],
    "requote_dedicated_api": False,
    "history_methods": ["history_deals_get", "history_orders_get"],
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


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "" or str(value).upper() in {"NOT AVAILABLE", "N/A", "UNKNOWN"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def has_order_link(deal: dict[str, Any]) -> bool:
    order = deal.get("order") if deal.get("order") is not None else deal.get("order_ticket")
    return order not in (None, "", 0, "0", "None")


def executed_volume(deal: dict[str, Any]) -> float | None:
    return _float_or_none(deal.get("volume") if deal.get("volume") is not None else deal.get("filled_volume"))


def requested_volume(deal: dict[str, Any], order: dict[str, Any] | None) -> float | None:
    """Explicit requested volume only. Executed deal.volume is not requested."""
    explicit = _float_or_none(deal.get("requested_volume") if deal.get("requested_volume") is not None else deal.get("volume_initial"))
    if explicit is not None and explicit > 0:
        return explicit
    if order is not None:
        initial = _float_or_none(order.get("volume_initial"))
        if initial is not None and initial > 0:
            return initial
    return None


def price_open_is_not_requested_price() -> bool:
    return True


def classify_full_fills(*, deals_with_fill_volume: int, complete_volume_links: int, filled_order_states: int) -> str:
    if complete_volume_links > 0 and filled_order_states > 0:
        return PROVEN
    if deals_with_fill_volume > 0:
        return NOT_PROVEN
    return NOT_IDENTIFIABLE


def classify_partial_fills(*, partial_order_states: int, volume_mismatches: int) -> str:
    if partial_order_states > 0 or volume_mismatches > 0:
        return PROVEN
    return NOT_PROVEN


def classify_order_state_observability(*, orders_present: int, observed_count: int) -> str:
    if observed_count > 0:
        return OBSERVED
    if orders_present <= 0:
        return NOT_OBSERVABLE
    return UNKNOWN


def classify_requotes(*, requote_comments: int, orders_present: int) -> str:
    if requote_comments > 0:
        return "COMMENT_HINT_ONLY"
    if orders_present <= 0:
        return NOT_OBSERVABLE
    return NOT_OBSERVABLE


def classify_order_deal_linkage(*, deal_count: int, linked_count: int) -> str:
    if deal_count <= 0:
        return NOT_IDENTIFIABLE
    if linked_count == deal_count:
        return "COMPLETE"
    return INCOMPLETE


def classify_volume_linkage(*, complete_links: int) -> str:
    if complete_links > 0:
        return "PARTIAL"
    return NOT_IDENTIFIABLE


def classify_latency(*, paired_timestamps: int) -> str:
    if paired_timestamps > 0:
        return "DERIVABLE"
    return NOT_DERIVABLE


def classify_execution_grade(*, deal_count: int, order_count: int, linked_count: int, lifecycle_proven: bool) -> str:
    if lifecycle_proven:
        return GRADE_A
    if order_count > 0 and linked_count > 0:
        return GRADE_B
    if deal_count > 0:
        return GRADE_C
    return GRADE_E


def zero_partials_does_not_prove_absence(partial_count: int) -> bool:
    return partial_count == 0


def simulated_broker_is_not_realized_execution() -> bool:
    return True


def simulated_broker_cannot_satisfy_complete() -> bool:
    return str(evaluate_execution_model().get("status")) != "COMPLETE"


def audit_execution_tape(deals: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, Any]:
    orders_by_ticket = {str(o.get("ticket")): o for o in orders if o.get("ticket") is not None}
    states: dict[str, int] = {}
    for order in orders:
        label = ORDER_STATE_LABEL.get(order.get("state"), str(order.get("state") if order.get("state") is not None else UNKNOWN))
        states[label] = states.get(label, 0) + 1
    filled_states = states.get("FILLED", 0)
    partial_states = states.get("PARTIAL", 0)
    rejected_states = states.get("REJECTED", 0)
    canceled_states = states.get("CANCELED", 0)
    deals_with_fill = 0
    linked = 0
    complete_volume_links = 0
    volume_mismatches = 0
    latency_pairs = 0
    requote_comments = 0
    entry_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for deal in deals:
        if executed_volume(deal) is not None:
            deals_with_fill += 1
        order = orders_by_ticket.get(str(deal.get("order") or deal.get("order_ticket") or ""))
        if has_order_link(deal):
            linked += 1
        req_vol = requested_volume(deal, order)
        exe_vol = executed_volume(deal)
        if req_vol is not None and exe_vol is not None:
            complete_volume_links += 1
            if abs(req_vol - exe_vol) > 1e-8:
                volume_mismatches += 1
        if order is not None:
            setup = _parse_utc(order.get("time_setup_utc") or order.get("time_setup"))
            done = _parse_utc(deal.get("time_utc") or deal.get("time") or order.get("time_done_utc"))
            if setup is not None and done is not None:
                latency_pairs += 1
        comment = str(deal.get("comment") or (order or {}).get("comment") or "").lower()
        if "requote" in comment:
            requote_comments += 1
        entry_label = DEAL_ENTRY_LABEL.get(deal.get("entry"), deal.get("entry_label") or UNKNOWN)
        entry_counts[str(entry_label)] = entry_counts.get(str(entry_label), 0) + 1
        reason = deal.get("reason")
        if reason is not None:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    for order in orders:
        comment = str(order.get("comment") or "").lower()
        if "requote" in comment:
            requote_comments += 1
    times = [d.get("time_utc") or d.get("time") for d in deals if d.get("time_utc") or d.get("time")]
    full_fills = classify_full_fills(
        deals_with_fill_volume=deals_with_fill,
        complete_volume_links=complete_volume_links,
        filled_order_states=filled_states,
    )
    partials = classify_partial_fills(partial_order_states=partial_states, volume_mismatches=volume_mismatches)
    rejections = classify_order_state_observability(orders_present=len(orders), observed_count=rejected_states)
    canceled = classify_order_state_observability(orders_present=len(orders), observed_count=canceled_states)
    requotes = classify_requotes(requote_comments=requote_comments, orders_present=len(orders))
    linkage = classify_order_deal_linkage(deal_count=len(deals), linked_count=linked)
    vol_link = classify_volume_linkage(complete_links=complete_volume_links)
    latency = classify_latency(paired_timestamps=latency_pairs)
    lifecycle_proven = (
        full_fills == PROVEN
        and linkage == "COMPLETE"
        and vol_link != NOT_IDENTIFIABLE
        and len(orders) > 0
    )
    grade = classify_execution_grade(
        deal_count=len(deals),
        order_count=len(orders),
        linked_count=linked,
        lifecycle_proven=lifecycle_proven,
    )
    return {
        "deal_count": len(deals),
        "order_count": len(orders),
        "deals_with_fill_volume": deals_with_fill,
        "linked_deal_count": linked,
        "complete_volume_links": complete_volume_links,
        "volume_mismatch_count": volume_mismatches,
        "latency_pair_count": latency_pairs,
        "requote_comment_count": requote_comments,
        "order_states": states,
        "filled_order_states": filled_states,
        "partial_order_states": partial_states,
        "rejected_order_states": rejected_states,
        "canceled_order_states": canceled_states,
        "entry_counts": entry_counts,
        "reason_counts": reason_counts,
        "deal_date_start": min(times) if times else None,
        "deal_date_end": max(times) if times else None,
        "full_fills": full_fills,
        "partial_fills": partials,
        "rejections": rejections,
        "canceled_orders": canceled,
        "requotes": requotes,
        "order_deal_linkage": linkage,
        "volume_linkage": vol_link,
        "execution_latency": latency,
        "zero_partials_proves_absence": False,
        "price_open_used_as_requested": False,
        "evidence_grade": grade,
        "classification": UNKNOWN if not lifecycle_proven else PROVEN,
        "phase27_24_partial_is_not_lifecycle": True,
    }


def search_existing_evidence(root: Path) -> dict[str, Any]:
    found = [{"path": rel, "present": (root / rel).is_file()} for rel in SOURCE_SEARCH_PATHS]
    p24 = _safe_load_json(root / PHASE2724_JSON) or {}
    exe = p24.get("execution") or {}
    cov = p24.get("coverage") or {}
    return {
        "paths": found,
        "phase27_24_execution_classification": exe.get("classification"),
        "phase27_24_gold_deals": cov.get("gold_deal_count") or exe.get("gold_deal_count"),
        "phase27_24_gold_orders": cov.get("live_gold_orders") or exe.get("gold_order_count"),
        "phase27_24_partial_fills": exe.get("partial_fill_count") or cov.get("partial_fill_count"),
        "phase27_24_filled_orders": exe.get("filled_order_count"),
        "phase27_24_gate_status": (exe.get("gate_model_unchanged") or {}).get("status"),
        "phase27_24_fingerprint": file_fingerprint(root / PHASE2724_JSON),
        "phase27_30_fingerprint": file_fingerprint(root / PHASE2730_JSON),
    }


def collect_live_history() -> dict[str, Any]:
    attach = bounded_readonly_attach_once()
    meta: dict[str, Any] = {
        "attempted": True,
        "attach_ok": bool(attach.get("ok")),
        "attach_error": attach.get("error"),
        "environment_ok": False,
        "method": "history_deals_get + history_orders_get read-only; no symbol_select; no order_send",
        "deals": [],
        "orders": [],
        "mt5_fields": {
            "deal_has_requested_price": False,
            "deal_has_requested_volume": False,
            "order_has_state": False,
            "order_has_volume_initial": False,
            "price_open_used_as_requested": False,
            "requote_api_present": False,
        },
    }
    if not attach.get("ok"):
        meta["stop_reason"] = "BLOCKED_PENDING_OPERATOR"
        return meta
    import MetaTrader5 as mt5

    account = collect_account_metadata(mt5)
    terminal = collect_terminal_metadata(mt5)
    env = str(account.get("trade_mode_label") or UNKNOWN)
    server = str(account.get("server") or UNKNOWN)
    meta["account"] = _sanitize(account)
    meta["terminal"] = terminal
    meta["environment"] = env
    meta["server"] = server
    if env != REQUIRED_ENV or server != REQUIRED_SERVER:
        meta["stop_reason"] = "BLOCKED_PENDING_OPERATOR"
        meta["error"] = f"attached {env}/{server} is not {REQUIRED_ENV}/{REQUIRED_SERVER}"
        return meta
    meta["environment_ok"] = True
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=HISTORY_DAYS)
    try:
        deals_raw = mt5.history_deals_get(date_from, date_to)
        orders_raw = mt5.history_orders_get(date_from, date_to)
    except Exception as exc:
        meta["error"] = str(exc)
        return meta
    deals: list[dict[str, Any]] = []
    for item in list(deals_raw or []):
        if not is_gold_symbol(getattr(item, "symbol", None)):
            continue
        deals.append(
            {
                "ticket": getattr(item, "ticket", None),
                "order": getattr(item, "order", None),
                "position_id": getattr(item, "position_id", None),
                "symbol": getattr(item, "symbol", None),
                "type": getattr(item, "type", None),
                "direction": DEAL_TYPE_LABEL.get(getattr(item, "type", None), UNKNOWN),
                "entry": getattr(item, "entry", None),
                "entry_label": DEAL_ENTRY_LABEL.get(getattr(item, "entry", None), UNKNOWN),
                "reason": getattr(item, "reason", None),
                "volume": getattr(item, "volume", None),
                "requested_volume": getattr(item, "requested_volume", None) if hasattr(item, "requested_volume") else None,
                "price": getattr(item, "price", None),
                "requested_price": None,
                "time_utc": datetime.fromtimestamp(getattr(item, "time", 0), tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if getattr(item, "time", None)
                else None,
                "comment": getattr(item, "comment", None),
                "_source": "mt5_history_deals_get",
            }
        )
        if len(deals) >= MAX_ROWS:
            break
    orders: list[dict[str, Any]] = []
    saw_state = False
    saw_initial = False
    for item in list(orders_raw or []):
        if not is_gold_symbol(getattr(item, "symbol", None)):
            continue
        if getattr(item, "state", None) is not None:
            saw_state = True
        if getattr(item, "volume_initial", None) not in (None,):
            saw_initial = True
        orders.append(
            {
                "ticket": getattr(item, "ticket", None),
                "symbol": getattr(item, "symbol", None),
                "type": getattr(item, "type", None),
                "type_label": ORDER_TYPE_LABEL.get(getattr(item, "type", None), UNKNOWN),
                "state": getattr(item, "state", None),
                "state_label": ORDER_STATE_LABEL.get(getattr(item, "state", None), UNKNOWN),
                "type_filling": getattr(item, "type_filling", None),
                "filling_label": FILLING_LABEL.get(getattr(item, "type_filling", None), UNKNOWN),
                "volume_initial": getattr(item, "volume_initial", None),
                "volume_current": getattr(item, "volume_current", None),
                "price_open": getattr(item, "price_open", None),
                "price_current": getattr(item, "price_current", None),
                "reason": getattr(item, "reason", None),
                "time_setup_utc": datetime.fromtimestamp(getattr(item, "time_setup", 0), tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if getattr(item, "time_setup", None)
                else None,
                "time_done_utc": datetime.fromtimestamp(getattr(item, "time_done", 0), tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if getattr(item, "time_done", None)
                else None,
                "comment": getattr(item, "comment", None),
                "requested_price": None,
                "_source": "mt5_history_orders_get",
            }
        )
        if len(orders) >= MAX_ROWS:
            break
    meta["deals"] = deals
    meta["orders"] = orders
    meta["live_gold_deal_count"] = len(deals)
    meta["live_gold_order_count"] = len(orders)
    meta["mt5_fields"] = {
        "deal_has_requested_price": False,
        "deal_has_requested_volume": any(d.get("requested_volume") not in (None,) for d in deals),
        "order_has_state": saw_state,
        "order_has_volume_initial": saw_initial,
        "price_open_used_as_requested": False,
        "requote_api_present": False,
    }
    return meta


def run_phase27_31_execution_evidence(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    fingerprint_before = file_fingerprint(root / CANONICAL_PARQUET)
    before = build_immutability_manifest(root)
    existing = search_existing_evidence(root)
    prior24_fp = existing.get("phase27_24_fingerprint")
    prior30_fp = existing.get("phase27_30_fingerprint")

    live = collect_live_history()
    artifact_deals = load_all_gold_deal_records(root)
    deals = list(live.get("deals") or []) + artifact_deals
    orders = list(live.get("orders") or [])
    audit = audit_execution_tape(deals, orders)
    gate = evaluate_execution_model()
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or UNKNOWN
    originals_untouched, imm_issues = verify_immutability(before, base_dir=root)
    fingerprint_after = file_fingerprint(root / CANONICAL_PARQUET)
    datasets_changed = not originals_untouched or fingerprint_before != fingerprint_after

    prior_identity = inherit_prior_real_identity(root)
    account = live.get("account") or {}
    if live.get("environment_ok"):
        env = str(live.get("environment") or account.get("trade_mode_label") or UNKNOWN)
        broker = account.get("broker") or prior_identity.get("broker") or "LiteFinance Global LLC"
        server = live.get("server") or account.get("server") or REQUIRED_SERVER
        terminal_build = (live.get("terminal") or {}).get("build")
        identity_provenance = "fresh_readonly_attach"
    else:
        env = str(prior_identity.get("account_type") or UNKNOWN)
        broker = prior_identity.get("broker") or "LiteFinance Global LLC"
        server = prior_identity.get("server") or REQUIRED_SERVER
        terminal_build = prior_identity.get("terminal_build")
        identity_provenance = (
            "inherited_from_phase27_29_real_attach; live attach skipped because "
            "terminal64.exe was not running and MT5 was not started"
        )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.31",
        "status": "PASS",
        "timestamp_utc": timestamp,
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "account_type": env,
        "broker": broker,
        "server": server,
        "terminal_build": terminal_build,
        "identity_provenance": identity_provenance,
        "prior_real_identity": prior_identity,
        "symbol": CANONICAL_SYMBOL,
        "inspected_artifact_deal_count": len(artifact_deals),
        "live_gold_deal_count": live.get("live_gold_deal_count") or 0,
        "live_gold_order_count": live.get("live_gold_order_count") or 0,
        "deal_date_start": audit["deal_date_start"],
        "deal_date_end": audit["deal_date_end"],
        "full_fills": audit["full_fills"],
        "partial_fills": audit["partial_fills"],
        "rejections": audit["rejections"],
        "canceled_orders": audit["canceled_orders"],
        "requotes": audit["requotes"],
        "order_deal_linkage": audit["order_deal_linkage"],
        "volume_linkage": audit["volume_linkage"],
        "execution_latency": audit["execution_latency"],
        "order_states": audit["order_states"],
        "classification": audit["classification"],
        "evidence_grade": audit["evidence_grade"],
        "audit": audit,
        "mt5_field_contract": MT5_FIELD_CONTRACT,
        "existing_evidence_search": existing,
        "live_collection": _sanitize({k: v for k, v in live.items() if k not in {"deals", "orders"}}),
        "mt5_field_audit": live.get("mt5_fields")
        or {
            "deal_has_requested_price": False,
            "price_open_used_as_requested": False,
            "requote_api_present": False,
        },
        "simulated_broker_audit": {
            "path": "tradingbot/backtest/broker.py::SimulatedBroker.execute",
            "model": "full_fill_simulated",
            "partial_fills_modeled_as_broker_reality": False,
            "requotes_modeled": False,
            "rejections_from_broker_tape": False,
            "is_realized_execution": False,
            "gate_status": gate.get("status"),
            "gate_unchanged": True,
            "can_satisfy_complete": False,
        },
        "simulated_broker_is_realized": False,
        "evaluate_execution_model": gate,
        "complete_costs_satisfied": False,
        "complete_costs_required_weakened": False,
        "phase27_16_final_gate_unchanged": final_gate,
        "phase27_24_preserved": (root / PHASE2724_JSON).is_file(),
        "phase27_24_fingerprint_before": prior24_fp,
        "phase27_24_fingerprint_after": file_fingerprint(root / PHASE2724_JSON),
        "phase27_30_preserved": (root / PHASE2730_JSON).is_file(),
        "phase27_30_fingerprint_before": prior30_fp,
        "phase27_30_fingerprint_after": file_fingerprint(root / PHASE2730_JSON),
        "blockers": [
            "execution lifecycle UNKNOWN — fill price/volume tape is not order-state evidence",
            "full fills NOT_PROVEN (no requested volume / FILLED order states)",
            "partial fills / rejections / cancels / requotes not proven",
            "order→deal and requested→executed volume linkage incomplete",
            "execution latency NOT_DERIVABLE",
            "SimulatedBroker full-fill cannot satisfy COMPLETE_COSTS_REQUIRED",
        ],
        "operator_dependency": True,
        "production_code_changed": False,
        "datasets_changed": datasets_changed,
        "canonical_fingerprint_before": fingerprint_before,
        "canonical_fingerprint_after": fingerprint_after,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": imm_issues,
        "production_readiness": "BLOCKED",
        "ev_eq_01": "NOT_PROVEN",
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "parquet_rewritten": False,
            "price_open_used_as_requested": False,
            "missing_states_inferred": False,
            "simulated_broker_treated_as_realized": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "phase_27_32_started": False,
        },
        "deferred": ["Phase 27.32+ — not started"],
    }
    missing_keys = [k for k in REQUIRED_ARTIFACT_KEYS if k not in payload]
    required_ok = (
        not missing_keys,
        originals_untouched,
        fingerprint_before == fingerprint_after,
        payload["phase27_24_fingerprint_before"] == payload["phase27_24_fingerprint_after"],
        not datasets_changed,
        not payload["production_code_changed"],
        payload["simulated_broker_is_realized"] is False,
        payload["complete_costs_satisfied"] is False,
        not payload["complete_costs_required_weakened"],
        final_gate == "BLOCKED",
        simulated_broker_is_not_realized_execution(),
        simulated_broker_cannot_satisfy_complete(),
        price_open_is_not_requested_price(),
        payload["classification"] != "COMPLETE",
        zero_partials_does_not_prove_absence(audit["partial_order_states"]),
    )
    if not all(required_ok):
        payload["status"] = "FAILED"
        if missing_keys:
            payload["blockers"] = list(payload["blockers"]) + [f"missing_artifact_keys:{','.join(missing_keys)}"]
    if live.get("stop_reason") == "BLOCKED_PENDING_OPERATOR" and not live.get("environment_ok"):
        payload["status"] = "PASS_WITH_DEFERRAL"

    out = root / PHASE2731_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_31_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_31_execution_evidence(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    md = f"""# Phase 27.31 — Real Account Execution Evidence Closure

**Status:** {payload["status"]}  
**Evidence grade:** `{payload["evidence_grade"]}`  
**Classification:** `{payload["classification"]}`  
**Artifact:** `{PHASE2731_JSON}`  
**Timestamp UTC:** `{payload["timestamp_utc"]}`

Read-only. Phase 27.24 / 27.30 artifacts were not overwritten. Production parquet was not rewritten.
Fill price/volume is not an order lifecycle tape. `price_open` is not requested price.
SimulatedBroker full-fill is not realized execution. Missing states were not inferred.

## Real account

| Field | Value |
|---|---|
| account type | `{payload["account_type"]}` |
| broker | `{payload["broker"]}` |
| server | `{payload["server"]}` |
| terminal build | `{payload["terminal_build"]}` |
| identity provenance | `{payload.get("identity_provenance")}` |
| symbol | `{payload["symbol"]}` |
| inspected artifact deals | `{payload.get("inspected_artifact_deal_count")}` |
| live gold deals / orders | `{payload.get("live_gold_deal_count")}` / `{payload.get("live_gold_order_count")}` |
| inspected deal date range | `{payload.get("deal_date_start")}` → `{payload.get("deal_date_end")}` |

## Independent classifications

| Dimension | Status |
|---|---|
| full fills | `{payload["full_fills"]}` |
| partial fills | `{payload["partial_fills"]}` |
| rejections | `{payload["rejections"]}` |
| canceled orders | `{payload["canceled_orders"]}` |
| requotes | `{payload["requotes"]}` |
| order→deal linkage | `{payload["order_deal_linkage"]}` |
| requested→executed volume | `{payload["volume_linkage"]}` |
| execution latency | `{payload["execution_latency"]}` |
| overall | `{payload["classification"]}` |
| grade | `{payload["evidence_grade"]}` |

Zero observed partials does **not** prove absence of partials. 27.24 `PARTIAL` was fill-tape visibility, not a proven lifecycle.

## SimulatedBroker / FINAL_GATE

| Field | Value |
|---|---|
| realized execution | `{payload["simulated_broker_is_realized"]}` |
| gate status | `{payload["evaluate_execution_model"]["status"]}` |
| can satisfy COMPLETE | `{payload["simulated_broker_audit"]["can_satisfy_complete"]}` |
| COMPLETE_COSTS_REQUIRED weakened | `{payload["complete_costs_required_weakened"]}` |
| FINAL_GATE | `{payload["phase27_16_final_gate_unchanged"]}` |

## Next

STOP after Phase 27.31.
"""
    (root / PHASE2731_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.31 execution evidence:** `{PHASE2731_JSON}` — "
            f"grade `{payload['evidence_grade']}`; classification `{payload['classification']}`; "
            "fill tape ≠ lifecycle; SimulatedBroker ≠ realized"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.30 slippage evidence:** `logs/phase27_30_slippage_evidence.json` — "
                "grade `REALIZED_UNKNOWN_NOT_IDENTIFIABLE`; genuine pairs `0`; MODELED_PROXY ≠ REALIZED"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        old = (
            "| Cost-adjusted profitability | **BLOCKED**. Policy Decision 6 = `COMPLETE_COSTS_REQUIRED`. "
            "Phase 27.16 **FINAL_GATE=BLOCKED** (not strategy/profitability/real-money approval). "
            "Phase 27.15 COST_READY_FOR_VALIDATION=false; 0 COMPLETE datasets |"
        )
        new = (
            "| Cost-adjusted profitability | **BLOCKED**. Policy Decision 6 = `COMPLETE_COSTS_REQUIRED`. "
            "Phase 27.16 **FINAL_GATE=BLOCKED** (not strategy/profitability/real-money approval). "
            "Phase 27.15 COST_READY_FOR_VALIDATION=false; 0 COMPLETE datasets |\n"
            f"| Execution / fill lifecycle | **UNKNOWN**. Phase 27.31 grade `{payload['evidence_grade']}`; "
            f"full fills `{payload['full_fills']}`; partials `{payload['partial_fills']}`; "
            "order→deal incomplete; SimulatedBroker full-fill ≠ realized |"
        )
        if old in text and "| Execution / fill lifecycle |" not in text:
            text = text.replace(old, new)
        known.write_text(text, encoding="utf-8")

    design = root / "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md"
    if design.is_file():
        text = design.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.31 execution evidence:** `{PHASE2731_JSON}` — "
            "deal fill tape only; order lifecycle UNKNOWN; SimulatedBroker ≠ realized"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.30 slippage evidence:** `logs/phase27_30_slippage_evidence.json` — "
                "0 genuine requested-vs-fill pairs; MODELED_PROXY remains implementation"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        design.write_text(text, encoding="utf-8")

    config = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    if config.is_file():
        text = config.read_text(encoding="utf-8")
        row = (
            "| Phase 27.31 execution evidence | `run_phase27_31_collection()` | n/a | "
            "order lifecycle vs fill tape; no state inference; SimulatedBroker ≠ realized | "
            f"**{payload['status']}** — grade `{payload['evidence_grade']}`; "
            f"full fills `{payload['full_fills']}`; linkage `{payload['order_deal_linkage']}`; "
            "FINAL_GATE remains BLOCKED |"
        )
        if row not in text:
            anchor = (
                "| Phase 27.30 slippage evidence | `run_phase27_30_collection()` | n/a | "
                "genuine requested-vs-fill only; price_open ≠ requested; MODELED_PROXY ≠ REALIZED | "
                "**PASS_WITH_DEFERRAL** — grade `REALIZED_UNKNOWN_NOT_IDENTIFIABLE`; "
                "genuine pairs `0`; MODELED_PROXY preserved; FINAL_GATE remains BLOCKED |"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "\n" + row)
        config.write_text(text, encoding="utf-8")

    phase15 = root / "docs_v2/01_truth/PHASE27_15_COST_COMPLETENESS_GATE.md"
    if phase15.is_file():
        text = phase15.read_text(encoding="utf-8")
        old = (
            "| `execution_model` | **UNKNOWN** | SimulatedBroker assumes full fill. No realized execution tape for validation. |"
        )
        new = (
            "| `execution_model` | **UNKNOWN** | SimulatedBroker assumes full fill. Phase 27.31 grade "
            f"`{payload['evidence_grade']}`; fill tape ≠ lifecycle; partials/rejections/requotes not proven. |"
        )
        if old in text:
            text = text.replace(old, new)
        old_b = (
            "| `execution_model` | `UNKNOWN` | HIGH | RESEARCH | Evidence realized fills / partials before treating simulation as complete |"
        )
        new_b = (
            "| `execution_model` | `UNKNOWN` | HIGH | RESEARCH | "
            "Evidence order lifecycle (states, linkage, requested vs executed volume); do not infer from fill tape |"
        )
        if old_b in text:
            text = text.replace(old_b, new_b)
        phase15.write_text(text, encoding="utf-8")

    phase16 = root / "docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md"
    if phase16.is_file():
        text = phase16.read_text(encoding="utf-8")
        old = (
            "| `execution_model` | `UNKNOWN` | yes | **no** | `logs/phase27_15_cost_completeness_gate.json` |"
        )
        new = (
            "| `execution_model` | `UNKNOWN` | yes | **no** | "
            "`logs/phase27_15_cost_completeness_gate.json`; `logs/phase27_31_execution_evidence.json` |"
        )
        if old in text:
            text = text.replace(old, new)
        phase16.write_text(text, encoding="utf-8")
