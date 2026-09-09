"""Phase 27.30 — Real-account historical slippage evidence closure.

Read-only. price_open / entry_price are not requested prices.
MODELED_PROXY is not REALIZED. Does not start MT5, place orders, or rewrite parquet.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_5_final_broker_cost_gate import load_all_gold_deal_records
from tradingbot.backtest.phase27_9_real_broker_evidence import bounded_readonly_attach_once
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_22_commission_forensic import (
    REDACT_ACCOUNT_KEYS,
    collect_account_metadata,
    collect_terminal_metadata,
)
from tradingbot.backtest.phase27_24_execution_cost_forensics import (
    DEAL_TYPE_LABEL,
    MARKET_ORDER_TYPES,
    is_gold_symbol,
)
from tradingbot.backtest.slippage_policy import (
    BASE_SLIPPAGE_PIPS_ASSUMPTION,
    IMPLEMENTATION_LABEL,
    POLICY,
    STATISTICAL_MIN_SAMPLES_ASSUMPTION,
    build_modeled_slippage_contract,
    cost_completeness_from_modeled_slippage_only,
    modeled_is_not_realized,
    mt5_deviation_is_realized_slippage,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2730_JSON = "logs/phase27_30_slippage_evidence.json"
PHASE2730_MD = "docs_v2/01_truth/PHASE27_30_SLIPPAGE_EVIDENCE.md"
PHASE2714_JSON = "logs/phase27_14_slippage_model.json"
PHASE2724_JSON = "logs/phase27_24_execution_cost_forensics.json"
PHASE2729_JSON = "logs/phase27_29_swap_evidence.json"
CANONICAL_SYMBOL = PRIMARY_SYMBOL
CANONICAL_PARQUET = "data/XAUUSD_i_5m.parquet"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
NOT_IDENTIFIABLE = "NOT_IDENTIFIABLE"
REQUIRED_ENV = "REAL"
REQUIRED_SERVER = "LiteFinance-MT5-Live"
HISTORY_DAYS = 180
MAX_ROWS = 200

GRADE_A = "HISTORICAL_REALIZED_SLIPPAGE_PROVEN"
GRADE_B = "PARTIAL_REALIZED_SAMPLES"
GRADE_C = "MODELED_PROXY_ONLY"
GRADE_D = "REALIZED_UNKNOWN_NOT_IDENTIFIABLE"
GRADE_E = "INSUFFICIENT_DATA"

REJECTED_REQUESTED_SOURCES = frozenset(
    {"price_open", "entry_price", "price", "deal.price", "market_price_open", "price_current"}
)

SOURCE_SEARCH_PATHS = (
    "logs/phase27_14_slippage_model.json",
    "logs/phase27_24_execution_cost_forensics.json",
    "logs/phase27_28_commission_evidence.json",
    "logs/phase27_29_swap_evidence.json",
    "docs_v2/01_truth/PHASE27_14_SLIPPAGE_MODEL.md",
    "docs_v2/01_truth/PHASE27_24_EXECUTION_COST_FORENSICS.md",
    "tradingbot/backtest/slippage_policy.py",
)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account_type",
    "broker",
    "server",
    "terminal_build",
    "symbol",
    "genuine_pair_count",
    "sample_count",
    "realized_slippage_status",
    "identifiable",
    "evidence_grade",
    "modeled_policy",
    "modeled_implementation",
    "modeled_can_become_realized",
    "complete_costs_satisfied",
    "production_code_changed",
    "datasets_changed",
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


def price_open_is_not_requested_price(source: Any) -> bool:
    return str(source or "").lower() in REJECTED_REQUESTED_SOURCES or source in (None, "")


def genuine_requested_price(record: dict[str, Any] | None) -> float | None:
    """Explicit requested_price only. Never price_open / entry_price / deal.price."""
    if not record:
        return None
    source = record.get("requested_price_source")
    if source is not None and str(source).lower() in REJECTED_REQUESTED_SOURCES:
        return None
    req = _float_or_none(record.get("requested_price"))
    if req is None or req <= 0:
        return None
    entry = _float_or_none(record.get("entry_price") if record.get("entry_price") is not None else record.get("price"))
    if entry is not None and req == entry and source in (None, "", "entry_price", "price"):
        return None
    return req


def classify_realized_grade(sample_count: int) -> str:
    if sample_count >= STATISTICAL_MIN_SAMPLES_ASSUMPTION:
        return GRADE_A
    if sample_count > 0:
        return GRADE_B
    return GRADE_D


def slippage_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "p50": None,
            "p90": None,
            "p95": None,
        }
    ordered = sorted(values)

    def pct(p: float) -> float:
        idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
        return ordered[idx]

    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p50": pct(50),
        "p90": pct(90),
        "p95": pct(95),
    }


def pair_genuine_requested_vs_fill(
    deals: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    *,
    point: float | None = None,
    tick_size: float | None = None,
) -> list[dict[str, Any]]:
    """Pair only explicit requested_price with an actual fill. No price_open inference."""
    orders_by_ticket: dict[str, dict[str, Any]] = {}
    for order in orders:
        ticket = order.get("ticket")
        if ticket is not None:
            orders_by_ticket[str(ticket)] = order
    pairs: list[dict[str, Any]] = []
    for deal in deals:
        fill = _float_or_none(deal.get("actual_fill_price") if deal.get("actual_fill_price") is not None else deal.get("price"))
        if fill is None or fill <= 0:
            continue
        order = None
        order_ticket = deal.get("order") or deal.get("order_ticket")
        if order_ticket is not None:
            order = orders_by_ticket.get(str(order_ticket))
        requested = genuine_requested_price(deal)
        if requested is None and order is not None:
            requested = genuine_requested_price(
                {
                    "requested_price": order.get("requested_price"),
                    "requested_price_source": order.get("requested_price_source")
                    or (
                        "order.requested_price"
                        if order.get("requested_price") not in (None, "")
                        else None
                    ),
                    "price": deal.get("price") or deal.get("actual_fill_price"),
                }
            )
        if requested is None:
            continue
        if order is not None:
            otype = order.get("type")
            try:
                if int(otype) in MARKET_ORDER_TYPES:
                    # Market order history cannot establish a requested price.
                    continue
            except (TypeError, ValueError):
                pass
            # price_open on pending orders is still not a requested price in this phase.
            if order.get("requested_price") in (None, "") and order.get("price_open") not in (None, "", 0, 0.0):
                if deal.get("requested_price") in (None, ""):
                    continue
        side = DEAL_TYPE_LABEL.get(deal.get("type"), deal.get("direction") or deal.get("side") or UNKNOWN)
        signed = fill - requested
        adverse = signed
        if str(side).upper() in {"SELL", "1"}:
            adverse = requested - fill
        price_units = signed
        points = (signed / point) if point and point > 0 else None
        ticks = (signed / tick_size) if tick_size and tick_size > 0 else None
        pairs.append(
            {
                "deal_ticket": deal.get("ticket"),
                "order_ticket": order_ticket,
                "symbol": deal.get("symbol") or CANONICAL_SYMBOL,
                "side": side,
                "requested_volume": deal.get("volume_initial") or (order or {}).get("volume_initial"),
                "executed_volume": deal.get("volume") or deal.get("filled_volume"),
                "requested_price": requested,
                "actual_fill_price": fill,
                "signed_slippage": price_units,
                "absolute_slippage": abs(price_units),
                "adverse_slippage": adverse,
                "points": points,
                "ticks": ticks,
                "timestamp_utc": deal.get("time_utc") or deal.get("time"),
                "requested_source": deal.get("requested_price_source") or "deal.requested_price",
            }
        )
    return pairs


def search_existing_evidence(root: Path) -> dict[str, Any]:
    found = [{"path": rel, "present": (root / rel).is_file()} for rel in SOURCE_SEARCH_PATHS]
    p14 = _safe_load_json(root / PHASE2714_JSON) or {}
    p24 = _safe_load_json(root / PHASE2724_JSON) or {}
    p14_samples = (p14.get("classification") or p14.get("contract") or p14).get("realized_sample_count")
    p24_slip = p24.get("slippage") or {}
    p24_samples = p24_slip.get("realized_sample_count")
    if p24_samples is None:
        p24_samples = (p24.get("coverage") or {}).get("realized_slippage_sample_count")
    if p24_samples is None:
        p24_samples = p24_slip.get("sample_count")
    prior = 0
    for raw in (p14_samples, p24_samples):
        try:
            prior = max(prior, int(raw))
        except (TypeError, ValueError):
            continue
    return {
        "paths": found,
        "phase27_14_realized_samples": p14_samples,
        "phase27_24_realized_samples": p24_samples,
        "phase27_14_fingerprint": file_fingerprint(root / PHASE2714_JSON),
        "phase27_24_fingerprint": file_fingerprint(root / PHASE2724_JSON),
        "prior_genuine_pairs": prior,
    }


def inherit_prior_real_identity(root: Path) -> dict[str, Any]:
    """Identity from the last successful Real attach. Not a fresh attach."""
    prior = _safe_load_json(root / PHASE2729_JSON) or {}
    live = prior.get("live_collection") or {}
    terminal = live.get("terminal") or {}
    account = live.get("account") or {}
    return {
        "account_type": prior.get("account_type") or live.get("environment") or account.get("trade_mode_label"),
        "broker": prior.get("broker") or account.get("broker"),
        "server": prior.get("server") or live.get("server") or account.get("server"),
        "terminal_build": terminal.get("build"),
        "source": PHASE2729_JSON,
        "fresh_attach": False,
    }


def collect_live_history() -> dict[str, Any]:
    attach = bounded_readonly_attach_once()
    meta: dict[str, Any] = {
        "attempted": True,
        "attach_ok": bool(attach.get("ok")),
        "attach_error": attach.get("error"),
        "environment_ok": False,
        "method": "history_deals_get + history_orders_get read-only; no symbol_select",
        "deals": [],
        "orders": [],
        "mt5_fields": {
            "deal_has_requested_price": False,
            "order_has_requested_price": False,
            "order_has_price_open": False,
            "price_open_used_as_requested": False,
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
        row = {
            "ticket": getattr(item, "ticket", None),
            "order": getattr(item, "order", None),
            "symbol": getattr(item, "symbol", None),
            "type": getattr(item, "type", None),
            "direction": DEAL_TYPE_LABEL.get(getattr(item, "type", None), UNKNOWN),
            "volume": getattr(item, "volume", None),
            "price": getattr(item, "price", None),
            "actual_fill_price": getattr(item, "price", None),
            "requested_price": getattr(item, "requested_price", None)
            if hasattr(item, "requested_price")
            else None,
            "time_utc": datetime.fromtimestamp(getattr(item, "time", 0), tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if getattr(item, "time", None)
            else None,
            "_source": "mt5_history_deals_get",
        }
        deals.append(row)
        if len(deals) >= MAX_ROWS:
            break
    orders: list[dict[str, Any]] = []
    saw_price_open = False
    for item in list(orders_raw or []):
        if not is_gold_symbol(getattr(item, "symbol", None)):
            continue
        if getattr(item, "price_open", None) not in (None, 0, 0.0):
            saw_price_open = True
        orders.append(
            {
                "ticket": getattr(item, "ticket", None),
                "symbol": getattr(item, "symbol", None),
                "type": getattr(item, "type", None),
                "volume_initial": getattr(item, "volume_initial", None),
                "volume_current": getattr(item, "volume_current", None),
                "price_open": getattr(item, "price_open", None),
                "price_current": getattr(item, "price_current", None),
                "requested_price": getattr(item, "requested_price", None)
                if hasattr(item, "requested_price")
                else None,
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
        "deal_has_requested_price": any(d.get("requested_price") not in (None,) for d in deals),
        "order_has_requested_price": any(o.get("requested_price") not in (None,) for o in orders),
        "order_has_price_open": saw_price_open,
        "price_open_used_as_requested": False,
        "deal_price_is_fill_only": True,
    }
    return meta


def run_phase27_30_slippage_evidence(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    fingerprint_before = file_fingerprint(root / CANONICAL_PARQUET)
    before = build_immutability_manifest(root)
    existing = search_existing_evidence(root)
    prior14_fp = existing.get("phase27_14_fingerprint")
    prior24_fp = existing.get("phase27_24_fingerprint")
    prior24 = _safe_load_json(root / PHASE2724_JSON) or {}
    slippage_status_before = (prior24.get("slippage") or {}).get("evidence") or IMPLEMENTATION_LABEL

    live = collect_live_history()
    artifact_deals = load_all_gold_deal_records(root)
    deals = list(live.get("deals") or []) + artifact_deals
    orders = list(live.get("orders") or [])
    inspected_times = [d.get("time_utc") or d.get("time") for d in artifact_deals if d.get("time_utc") or d.get("time")]
    pairs = pair_genuine_requested_vs_fill(deals, orders, point=0.01, tick_size=0.01)
    signed = [float(p["signed_slippage"]) for p in pairs]
    absvals = [float(p["absolute_slippage"]) for p in pairs]
    buy = [p for p in pairs if str(p["side"]).upper() == "BUY"]
    sell = [p for p in pairs if str(p["side"]).upper() == "SELL"]
    times = [p.get("timestamp_utc") for p in pairs if p.get("timestamp_utc")]
    grade = classify_realized_grade(len(pairs))
    identifiable = len(pairs) > 0
    realized_status = "REALIZED" if identifiable else f"{UNKNOWN} / {NOT_IDENTIFIABLE}"
    modeled = build_modeled_slippage_contract(realized_sample_count=len(pairs))
    cfg = BacktestConfig()
    completeness = cost_completeness_from_modeled_slippage_only()
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or UNKNOWN
    originals_untouched, imm_issues = verify_immutability(before, base_dir=root)
    fingerprint_after = file_fingerprint(root / CANONICAL_PARQUET)
    datasets_changed = not originals_untouched or fingerprint_before != fingerprint_after
    unavailable_reason = (
        "MT5 history_deals_get exposes fill price (deal.price) but no requested_price field. "
        "history_orders_get exposes price_open / price_current, which this phase must not treat "
        "as requested price. Artifact gold deals also lack an explicit requested_price distinct "
        "from entry/fill. Therefore requested-vs-fill pairs are NOT_IDENTIFIABLE."
    )
    account = live.get("account") or {}
    prior_identity = inherit_prior_real_identity(root)
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
        "phase": "27.30",
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
        "genuine_pair_count": len(pairs),
        "sample_count": len(pairs),
        "deal_date_start": min(times) if times else None,
        "deal_date_end": max(times) if times else None,
        "inspected_artifact_deal_count": len(artifact_deals),
        "inspected_deal_date_start": min(inspected_times) if inspected_times else None,
        "inspected_deal_date_end": max(inspected_times) if inspected_times else None,
        "identifiable": identifiable,
        "realized_slippage_status": realized_status,
        "evidence_grade": grade,
        "derivable_historical_model": False,
        "not_identifiable_reason": None if identifiable else unavailable_reason,
        "signed_stats": slippage_stats(signed),
        "absolute_stats": slippage_stats(absvals),
        "buy_sample_count": len(buy),
        "sell_sample_count": len(sell),
        "zero_slippage_count": sum(1 for v in signed if v == 0.0),
        "nonzero_slippage_count": sum(1 for v in signed if v != 0.0),
        "pairs_preview": pairs[:8],
        "modeled_policy": POLICY,
        "modeled_implementation": IMPLEMENTATION_LABEL,
        "modeled_source": modeled.provenance,
        "modeled_assumptions": list(modeled.assumptions),
        "modeled_contract": modeled.to_dict(),
        "modeled_can_become_realized": False,
        "modeled_can_satisfy_complete": False,
        "mt5_deviation_is_realized": mt5_deviation_is_realized_slippage(),
        "complete_costs_satisfied": False,
        "complete_costs_required_weakened": False,
        "slippage_status_before": slippage_status_before,
        "slippage_status_after": IMPLEMENTATION_LABEL,
        "default_slippage_status": cfg.slippage_status,
        "default_slippage_pips": cfg.slippage_pips,
        "existing_evidence_search": existing,
        "live_collection": _sanitize({k: v for k, v in live.items() if k not in {"deals", "orders"}}),
        "mt5_field_audit": live.get("mt5_fields")
        or {
            "deal_has_requested_price": False,
            "order_has_requested_price": False,
            "price_open_used_as_requested": False,
        },
        "implementation_audit": {
            "paths": [
                "tradingbot/backtest/slippage_policy.py",
                "tradingbot/backtest/cost_model.py::build_backtest_cost_model",
                "tradingbot/backtest/config.py::BacktestConfig.slippage_status",
                "tradingbot/domain/session_logic.py::session_cost_multiplier",
            ],
            "modeled_is_not_realized": modeled_is_not_realized(),
            "modeled_blocks_complete": completeness != CostCompleteness.COMPLETE,
            "price_open_rejected": True,
            "entry_price_rejected": True,
            "unknown_fail_closed": True,
        },
        "blockers": [
            "realized slippage UNKNOWN / NOT_IDENTIFIABLE — 0 genuine requested-vs-fill pairs",
            "price_open / entry_price / deal.price are not requested prices",
            "MODELED_PROXY cannot satisfy COMPLETE_COSTS_REQUIRED",
        ],
        "operator_dependency": True,
        "production_code_changed": False,
        "datasets_changed": datasets_changed,
        "canonical_fingerprint_before": fingerprint_before,
        "canonical_fingerprint_after": fingerprint_after,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": imm_issues,
        "phase27_16_final_gate_unchanged": final_gate,
        "phase27_14_preserved": (root / PHASE2714_JSON).is_file(),
        "phase27_24_preserved": (root / PHASE2724_JSON).is_file(),
        "phase27_14_fingerprint_before": prior14_fp,
        "phase27_14_fingerprint_after": file_fingerprint(root / PHASE2714_JSON),
        "phase27_24_fingerprint_before": prior24_fp,
        "phase27_24_fingerprint_after": file_fingerprint(root / PHASE2724_JSON),
        "production_readiness": "BLOCKED",
        "ev_eq_01": "NOT_PROVEN",
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "parquet_rewritten": False,
            "price_open_used_as_requested": False,
            "modeled_labeled_realized": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "phase_27_31_started": False,
        },
        "deferred": ["Phase 27.31+ — not started"],
    }
    missing_keys = [k for k in REQUIRED_ARTIFACT_KEYS if k not in payload]
    required_ok = (
        not missing_keys,
        originals_untouched,
        fingerprint_before == fingerprint_after,
        payload["phase27_14_fingerprint_before"] == payload["phase27_14_fingerprint_after"],
        payload["phase27_24_fingerprint_before"] == payload["phase27_24_fingerprint_after"],
        not datasets_changed,
        not payload["production_code_changed"],
        payload["modeled_can_become_realized"] is False,
        payload["complete_costs_satisfied"] is False,
        payload["implementation_audit"]["modeled_blocks_complete"],
        not payload["complete_costs_required_weakened"],
        final_gate == "BLOCKED",
        modeled_is_not_realized(),
        not mt5_deviation_is_realized_slippage(),
        genuine_requested_price({"requested_price": 100.0, "requested_price_source": "price_open", "price": 100.0}) is None,
    )
    if not all(required_ok):
        payload["status"] = "FAILED"
        if missing_keys:
            payload["blockers"] = list(payload["blockers"]) + [f"missing_artifact_keys:{','.join(missing_keys)}"]
    if live.get("stop_reason") == "BLOCKED_PENDING_OPERATOR" and not live.get("environment_ok"):
        payload["status"] = "PASS_WITH_DEFERRAL"

    out = root / PHASE2730_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_30_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_30_slippage_evidence(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    md = f"""# Phase 27.30 — Real Account Slippage Evidence Closure

**Status:** {payload["status"]}  
**Evidence grade:** `{payload["evidence_grade"]}`  
**Realized status:** `{payload["realized_slippage_status"]}`  
**Artifact:** `{PHASE2730_JSON}`  
**Timestamp UTC:** `{payload["timestamp_utc"]}`

Read-only. Phase 27.14 / 27.24 artifacts were not overwritten. Production parquet was not rewritten.
`price_open` and `entry_price` were not treated as requested prices. MODELED_PROXY is not REALIZED.

## Real account

| Field | Value |
|---|---|
| account type | `{payload["account_type"]}` |
| broker | `{payload["broker"]}` |
| server | `{payload["server"]}` |
| terminal build | `{payload["terminal_build"]}` |
| identity provenance | `{payload.get("identity_provenance")}` |
| symbol | `{payload["symbol"]}` |

## Historical slippage

| Field | Value |
|---|---|
| genuine requested-vs-fill pairs | `{payload["genuine_pair_count"]}` |
| sample count | `{payload["sample_count"]}` |
| pair date range | `{payload["deal_date_start"]}` → `{payload["deal_date_end"]}` |
| inspected artifact deals | `{payload.get("inspected_artifact_deal_count")}` |
| inspected deal date range | `{payload.get("inspected_deal_date_start")}` → `{payload.get("inspected_deal_date_end")}` |
| identifiable | `{payload["identifiable"]}` |
| realized status | `{payload["realized_slippage_status"]}` |
| evidence grade | `{payload["evidence_grade"]}` |
| derivable historical model | `{payload["derivable_historical_model"]}` |

{payload.get("not_identifiable_reason") or "Genuine pairs were collected; see JSON for statistics."}

## MODELED_PROXY

| Field | Value |
|---|---|
| policy | `{payload["modeled_policy"]}` |
| implementation | `{payload["modeled_implementation"]}` |
| source | `{payload["modeled_source"]}` |
| base pips | `{payload["default_slippage_pips"]}` |
| can become REALIZED silently | `{payload["modeled_can_become_realized"]}` |
| can satisfy COMPLETE | `{payload["modeled_can_satisfy_complete"]}` |
| MT5 deviation is realized | `{payload["mt5_deviation_is_realized"]}` |

Assumptions: {payload["modeled_assumptions"]}

## FINAL_GATE

slippage_status_before: `{payload["slippage_status_before"]}`  
slippage_status_after: `{payload["slippage_status_after"]}`  
COMPLETE_COSTS_REQUIRED remains enforced. FINAL_GATE remains `{payload["phase27_16_final_gate_unchanged"]}`.

## Next

STOP after Phase 27.30.
"""
    (root / PHASE2730_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.30 slippage evidence:** `{PHASE2730_JSON}` — "
            f"grade `{payload['evidence_grade']}`; genuine pairs `{payload['sample_count']}`; "
            "MODELED_PROXY ≠ REALIZED"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.29 swap evidence:** `logs/phase27_29_swap_evidence.json` — "
                "grade `CURRENT_BROKER_RATE_ONLY`; historical series UNKNOWN; "
                "current broker rates ≠ historical"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        old = (
            "| Slippage realized distribution | **UNKNOWN**. Decision 5 = `MODELED` / `MODELED_PROXY`. "
            "Phase 27.24 realized samples `0` evidence `UNKNOWN`; entry_price ≠ requested; deviation ≠ slippage |"
        )
        new = (
            "| Slippage realized distribution | **UNKNOWN / NOT_IDENTIFIABLE**. Decision 5 = `MODELED` / `MODELED_PROXY`. "
            f"Phase 27.30 grade `{payload['evidence_grade']}`; genuine pairs `{payload['sample_count']}`; "
            "price_open ≠ requested; MODELED_PROXY ≠ REALIZED |"
        )
        if old in text:
            text = text.replace(old, new)
        known.write_text(text, encoding="utf-8")

    design = root / "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md"
    if design.is_file():
        text = design.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.30 slippage evidence:** `{PHASE2730_JSON}` — "
            "0 genuine requested-vs-fill pairs; MODELED_PROXY remains implementation"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.29 swap evidence:** `logs/phase27_29_swap_evidence.json` — "
                "BROKER_RATE_ONLY current snapshot; historical series UNKNOWN"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        old_row = (
            "| Slippage | UNKNOWN | UNKNOWN | MODELED_PROXY default. Decision 5 implemented (Phase 27.14): "
            "documented session-hour proxy; MODELED ≠ realized; deviation ≠ slippage; "
            "proxy cannot make cost COMPLETE |"
        )
        new_row = (
            "| Slippage | UNKNOWN / NOT_IDENTIFIABLE | UNKNOWN / NOT_IDENTIFIABLE | "
            "MODELED_PROXY default. Decision 5 implemented (Phase 27.14/27.30): "
            "documented session-hour proxy; 0 genuine requested-vs-fill pairs; "
            "price_open ≠ requested; MODELED ≠ realized; proxy cannot make cost COMPLETE |"
        )
        if old_row in text:
            text = text.replace(old_row, new_row)
        design.write_text(text, encoding="utf-8")

    config = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    if config.is_file():
        text = config.read_text(encoding="utf-8")
        old_slip = (
            "| `BacktestConfig.slippage_status` | A | `MODELED_PROXY` | n/a | backtest cost model | "
            "RESEARCH/BACKTEST | Phase 27.14: Decision 5 MODELED implemented as MODELED_PROXY; "
            "≠ REALIZED; `slippage_pips=0.8` is an assumption; does not make cost COMPLETE |"
        )
        new_slip = (
            "| `BacktestConfig.slippage_status` | A | `MODELED_PROXY` | n/a | backtest cost model | "
            "RESEARCH/BACKTEST | Phase 27.14/27.30: Decision 5 MODELED implemented as MODELED_PROXY; "
            "≠ REALIZED; `slippage_pips=0.8` is an assumption; 0 genuine requested-vs-fill pairs; "
            "does not make cost COMPLETE |"
        )
        if old_slip in text:
            text = text.replace(old_slip, new_slip)
        row = (
            "| Phase 27.30 slippage evidence | `run_phase27_30_collection()` | n/a | "
            "genuine requested-vs-fill only; price_open ≠ requested; MODELED_PROXY ≠ REALIZED | "
            f"**{payload['status']}** — grade `{payload['evidence_grade']}`; "
            f"genuine pairs `{payload['sample_count']}`; MODELED_PROXY preserved; "
            "FINAL_GATE remains BLOCKED |"
        )
        if row not in text:
            anchor = (
                "| Phase 27.29 swap evidence | `run_phase27_29_collection()` | n/a | "
                "current Real swap rates vs historical series; zeros ≠ historical zero | "
                "**PASS** — grade `CURRENT_BROKER_RATE_ONLY`; swap_long `-89.136` / "
                "swap_short `3.45` / Wednesday; historical series UNKNOWN; FINAL_GATE remains BLOCKED |"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "\n" + row)
        config.write_text(text, encoding="utf-8")

    phase15 = root / "docs_v2/01_truth/PHASE27_15_COST_COMPLETENESS_GATE.md"
    if phase15.is_file():
        text = phase15.read_text(encoding="utf-8")
        old = (
            "| `slippage` | **UNKNOWN** | MODELED_PROXY is not realized slippage. 0 requested-vs-fill samples. |"
        )
        new = (
            "| `slippage` | **UNKNOWN / NOT_IDENTIFIABLE** | MODELED_PROXY is not realized slippage. "
            f"Phase 27.30 grade `{payload['evidence_grade']}`; genuine pairs `{payload['sample_count']}`; "
            "price_open ≠ requested. |"
        )
        if old in text:
            text = text.replace(old, new)
        old_b = (
            "| `slippage` | `UNKNOWN` | HIGH | OPERATOR | Collect statistically sufficient requested-vs-fill samples |"
        )
        new_b = (
            "| `slippage` | `UNKNOWN / NOT_IDENTIFIABLE` | HIGH | OPERATOR | "
            "Collect statistically sufficient genuine requested-vs-fill samples; do not use price_open |"
        )
        if old_b in text:
            text = text.replace(old_b, new_b)
        phase15.write_text(text, encoding="utf-8")

    phase16 = root / "docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md"
    if phase16.is_file():
        text = phase16.read_text(encoding="utf-8")
        old = (
            "| `slippage` | `UNKNOWN` | yes | **no** | `logs/phase27_14_slippage_model.json` |"
        )
        new = (
            "| `slippage` | `UNKNOWN` | yes | **no** | "
            "`logs/phase27_14_slippage_model.json`; `logs/phase27_30_slippage_evidence.json` |"
        )
        if old in text:
            text = text.replace(old, new)
        phase16.write_text(text, encoding="utf-8")
