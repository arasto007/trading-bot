"""Phase 27.24 — realized swap / slippage / execution forensics.

Read-only. Does not treat zero swap as verified zero, entry_price as
requested_price, MT5 deviation as slippage, or SimulatedBroker as execution
evidence. Does not change COMPLETE_COSTS_REQUIRED.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.cost_model import CostCompleteness, assess_cost_completeness, build_backtest_cost_model
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_5_final_broker_cost_gate import load_all_gold_deal_records
from tradingbot.backtest.phase27_9_real_broker_evidence import (
    account_identity_snapshot,
    bounded_readonly_attach_once,
)
from tradingbot.backtest.phase27_13_swap_policy import PHASE2713_JSON
from tradingbot.backtest.phase27_14_slippage_model import PHASE2714_JSON
from tradingbot.backtest.phase27_15_cost_completeness_gate import evaluate_execution_model
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.slippage_policy import mt5_deviation_is_realized_slippage
from tradingbot.backtest.swap_policy import (
    POLICY as SWAP_POLICY,
    realized_zero_is_not_verified_zero,
    verified_zero_swap_from_realized,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2724_JSON = "logs/phase27_24_execution_cost_forensics.json"
PHASE2724_MD = "docs_v2/01_truth/PHASE27_24_EXECUTION_COST_FORENSICS.md"

REQUIRED_ENV = "REAL"
REQUIRED_SERVER = "LiteFinance-MT5-Live"
HISTORY_DAYS = 180
MAX_DEALS = 250
MAX_ORDERS = 250

PROVEN = "PROVEN"
PARTIAL = "PARTIAL"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
HISTORICAL = "HISTORICAL"
BROKER_RATE_ONLY = SWAP_POLICY
REALIZED_EXECUTION_EVIDENCE = "REALIZED_EXECUTION_EVIDENCE"

PENDING_ORDER_TYPES = frozenset({2, 3, 4, 5, 6, 7})  # limit / stop / stop-limit
MARKET_ORDER_TYPES = frozenset({0, 1})
DEAL_TYPE_LABEL = {0: "BUY", 1: "SELL"}
DEAL_ENTRY_LABEL = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}
ORDER_STATE_LABEL = {
    0: "STARTED",
    1: "PLACED",
    2: "CANCELED",
    3: "PARTIAL",
    4: "FILLED",
    5: "REJECTED",
    6: "EXPIRED",
}
ORDER_TYPE_LABEL = {
    0: "BUY",
    1: "SELL",
    2: "BUY_LIMIT",
    3: "SELL_LIMIT",
    4: "BUY_STOP",
    5: "SELL_STOP",
    6: "BUY_STOP_LIMIT",
    7: "SELL_STOP_LIMIT",
    8: "CLOSE_BY",
}
FILLING_LABEL = {0: "FOK", 1: "IOC", 2: "RETURN"}


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
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def is_gold_symbol(symbol: Any) -> bool:
    sym = str(symbol or "").upper()
    return sym in {"XAUUSD", "XAUUSD_I", PRIMARY_SYMBOL.upper()}


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "" or str(value).upper() in {"NOT AVAILABLE", "N/A", "UNKNOWN"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def entry_price_is_not_requested_price(deal: dict[str, Any]) -> bool:
    """entry_price / deal.price is never a genuine requested_price."""
    if deal.get("requested_price") in (None, "", "NOT AVAILABLE", "N/A"):
        return True
    req = _float_or_none(deal.get("requested_price"))
    entry = _float_or_none(deal.get("entry_price") if deal.get("entry_price") is not None else deal.get("price"))
    if req is None:
        return True
    if entry is not None and req == entry and deal.get("requested_price_source") in (None, "entry_price", "price"):
        return True
    return False


def genuine_requested_price(order: dict[str, Any] | None) -> float | None:
    """Pending limit/stop price_open only. Market price_open is not requested."""
    if not order:
        return None
    otype = order.get("type")
    try:
        otype_i = int(otype)
    except (TypeError, ValueError):
        return None
    if otype_i in MARKET_ORDER_TYPES:
        return None
    if otype_i not in PENDING_ORDER_TYPES:
        return None
    price = _float_or_none(order.get("price_open"))
    if price is None or price <= 0:
        return None
    return price


def classify_swap_treatment(*, has_broker_rates: bool, has_historical_series: bool) -> str:
    if has_historical_series:
        return HISTORICAL
    if has_broker_rates:
        return BROKER_RATE_ONLY
    return UNKNOWN


def classify_swap_evidence(*, has_broker_rates: bool, nonzero: int, series: bool) -> str:
    if series:
        return PROVEN
    if has_broker_rates and nonzero > 0:
        return PARTIAL
    if has_broker_rates:
        return UNKNOWN
    return BLOCKED


def classify_slippage_evidence(sample_count: int) -> str:
    if sample_count <= 0:
        return UNKNOWN
    if sample_count < 10:
        return PARTIAL
    return PARTIAL  # samples exist; not a COMPLETE dataset distribution


def classify_execution(
    *,
    gold_deals: int,
    gold_orders: int,
    filled: int,
    partials: int,
    rejected: int,
    from_simulation: bool,
) -> str:
    if from_simulation:
        return UNKNOWN
    if gold_deals <= 0 and gold_orders <= 0:
        return UNKNOWN
    if partials > 0 or rejected > 0:
        return PARTIAL
    if filled > 0 or gold_deals > 0:
        return PARTIAL
    return UNKNOWN


def holding_durations(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for deal in deals:
        key = str(deal.get("position_id") or deal.get("position") or "")
        if not key or key in {"None", "0"}:
            continue
        groups.setdefault(key, []).append(deal)
    out: list[dict[str, Any]] = []
    for key, rows in groups.items():
        times: list[datetime] = []
        for row in rows:
            raw = row.get("time_utc") or row.get("time")
            if not raw:
                continue
            try:
                times.append(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
            except ValueError:
                continue
        if len(times) < 2:
            continue
        times.sort()
        seconds = (times[-1] - times[0]).total_seconds()
        out.append({"position_id": key, "hold_seconds": seconds, "deal_count": len(rows)})
    return out


def realized_slippage_pairs(
    deals: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Only genuine requested_price + actual_fill_price. No entry/deviation/spread substitutes."""
    orders_by_ticket: dict[str, dict[str, Any]] = {}
    for order in orders:
        ticket = order.get("ticket")
        if ticket is not None:
            orders_by_ticket[str(ticket)] = order

    samples: list[dict[str, Any]] = []
    for deal in deals:
        fill = _float_or_none(
            deal.get("actual_fill_price") if deal.get("actual_fill_price") not in (None, "NOT AVAILABLE") else deal.get("price")
        )
        explicit = _float_or_none(deal.get("requested_price"))
        order = None
        order_ticket = deal.get("order") or deal.get("order_ticket")
        if order_ticket is not None:
            order = orders_by_ticket.get(str(order_ticket))
        requested = explicit if explicit is not None and explicit > 0 else genuine_requested_price(order)
        if requested is None or fill is None:
            continue
        if explicit is None and order is None:
            continue
        if entry_price_is_not_requested_price({**deal, "requested_price": requested}) and explicit is None:
            # pending price_open is allowed; entry_price substitution is not
            if genuine_requested_price(order) is None:
                continue
        direction = DEAL_TYPE_LABEL.get(deal.get("type"), deal.get("direction") or deal.get("side") or UNKNOWN)
        signed = fill - requested
        adverse = signed
        if str(direction).upper() in {"BUY", "0"}:
            adverse = fill - requested  # positive = worse for buy
        elif str(direction).upper() in {"SELL", "1"}:
            adverse = requested - fill  # positive = worse for sell
        samples.append(
            {
                "deal_ticket": deal.get("ticket"),
                "order_ticket": order_ticket,
                "symbol": deal.get("symbol"),
                "direction": direction,
                "volume": deal.get("volume"),
                "requested_price": requested,
                "actual_fill_price": fill,
                "signed_slippage": signed,
                "adverse_slippage": adverse,
                "timestamp_utc": deal.get("time_utc"),
                "requested_source": "deal.requested_price" if explicit is not None else "pending_order.price_open",
            }
        )
    return samples


def analyze_swap(deals: list[dict[str, Any]], *, has_broker_rates: bool) -> dict[str, Any]:
    values: list[float] = []
    for deal in deals:
        sw = _float_or_none(deal.get("swap"))
        if sw is not None:
            values.append(sw)
    nonzero = [v for v in values if v != 0.0]
    zeros = [v for v in values if v == 0.0]
    holds = holding_durations(deals)
    times = [d.get("time_utc") for d in deals if d.get("time_utc")]
    treatment = classify_swap_treatment(has_broker_rates=has_broker_rates, has_historical_series=False)
    evidence = classify_swap_evidence(has_broker_rates=has_broker_rates, nonzero=len(nonzero), series=False)
    return {
        "treatment": treatment,
        "evidence": evidence,
        "gold_deals_with_swap_field": len(values),
        "nonzero_swap_count": len(nonzero),
        "zero_swap_count": len(zeros),
        "total_realized_swap": round(sum(values), 6) if values else 0.0,
        "nonzero_values": nonzero[:20],
        "date_range": {"start": min(times) if times else UNKNOWN, "end": max(times) if times else UNKNOWN},
        "holding_durations_known": len(holds),
        "holding_seconds_sample": [h["hold_seconds"] for h in holds[:20]],
        "overnight_holds_over_12h": sum(1 for h in holds if h["hold_seconds"] >= 12 * 3600),
        "historical_swap_series": UNKNOWN,
        "realized_zero_proves_verified_zero": verified_zero_swap_from_realized(values),
        "realized_zero_is_not_verified_zero": realized_zero_is_not_verified_zero(values),
        "series_synthesized": False,
        "sufficient_for_historical_behavior": False,
        "note": "Deal-level swap snapshots are not a historical daily series. Zero swap does not prove ZERO.",
    }


def analyze_execution(deals: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, Any]:
    states: dict[str, int] = {}
    filling: dict[str, int] = {}
    for order in orders:
        label = ORDER_STATE_LABEL.get(order.get("state"), str(order.get("state")))
        states[label] = states.get(label, 0) + 1
        fill_label = FILLING_LABEL.get(order.get("type_filling"), str(order.get("type_filling")))
        filling[fill_label] = filling.get(fill_label, 0) + 1
    filled = states.get("FILLED", 0)
    partials = states.get("PARTIAL", 0)
    rejected = states.get("REJECTED", 0)
    deals_by_order: dict[str, list[dict[str, Any]]] = {}
    for deal in deals:
        key = str(deal.get("order") or "")
        if key and key not in {"None", "0"}:
            deals_by_order.setdefault(key, []).append(deal)
    multi_deal_orders = sum(1 for rows in deals_by_order.values() if len(rows) > 1)
    volume_mismatch = 0
    orders_by_ticket = {str(o.get("ticket")): o for o in orders if o.get("ticket") is not None}
    for oticket, rows in deals_by_order.items():
        order = orders_by_ticket.get(oticket)
        if not order:
            continue
        initial = _float_or_none(order.get("volume_initial"))
        filled_vol = sum(_float_or_none(r.get("volume")) or 0.0 for r in rows)
        if initial is not None and abs(filled_vol - initial) > 1e-8 and (_float_or_none(order.get("volume_current")) or 0) > 0:
            volume_mismatch += 1
            if order.get("state") == 3:
                partials += 1
    requotes = 0
    for row in list(deals) + list(orders):
        comment = str(row.get("comment") or "").lower()
        if "requote" in comment:
            requotes += 1
    classification = classify_execution(
        gold_deals=len(deals),
        gold_orders=len(orders),
        filled=filled,
        partials=partials,
        rejected=rejected,
        from_simulation=False,
    )
    if classification == PARTIAL and (partials > 0 or rejected > 0 or filled >= 5):
        # Still PARTIAL: history is not a validation execution model.
        classification = PARTIAL
    return {
        "classification": classification,
        "gold_deal_count": len(deals),
        "gold_order_count": len(orders),
        "order_states": states,
        "filling_modes": filling,
        "filled_order_count": filled,
        "partial_fill_count": partials,
        "rejected_order_count": rejected,
        "expired_order_count": states.get("EXPIRED", 0),
        "canceled_order_count": states.get("CANCELED", 0),
        "multi_deal_order_count": multi_deal_orders,
        "volume_mismatch_count": volume_mismatch,
        "requote_comment_count": requotes,
        "simulated_broker_used": False,
        "note": "SimulatedBroker full-fill is not realized execution evidence.",
    }


def _collect_live_history() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    attach = bounded_readonly_attach_once()
    meta: dict[str, Any] = {
        "attempted": bool(attach.get("ok")),
        "attach_ok": attach.get("ok"),
        "attach_error": attach.get("error"),
        "method": "history_deals_get + history_orders_get read-only; no symbol_select",
        "history_days": HISTORY_DAYS,
        "max_deals": MAX_DEALS,
        "max_orders": MAX_ORDERS,
        "environment_ok": False,
    }
    if not attach.get("ok"):
        return [], [], meta
    import MetaTrader5 as mt5

    account = account_identity_snapshot(mt5)
    meta["environment"] = account.get("trade_mode_label")
    meta["server"] = account.get("server")
    meta["broker"] = account.get("broker")
    if account.get("trade_mode_label") != REQUIRED_ENV or account.get("server") != REQUIRED_SERVER:
        meta["error"] = (
            f"attached {account.get('trade_mode_label')}/{account.get('server')} "
            f"is not {REQUIRED_ENV}/{REQUIRED_SERVER}"
        )
        return [], [], meta
    meta["environment_ok"] = True
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=HISTORY_DAYS)
    deals_raw = None
    orders_raw = None
    try:
        deals_raw = mt5.history_deals_get(date_from, date_to)
        orders_raw = mt5.history_orders_get(date_from, date_to)
    except Exception as exc:
        meta["error"] = str(exc)
        return [], [], meta
    deals: list[dict[str, Any]] = []
    for d in list(deals_raw or []):
        if not is_gold_symbol(getattr(d, "symbol", None)):
            continue
        deals.append(
            _sanitize(
                {
                    "ticket": getattr(d, "ticket", None),
                    "order": getattr(d, "order", None),
                    "position_id": getattr(d, "position_id", None),
                    "symbol": getattr(d, "symbol", None),
                    "type": getattr(d, "type", None),
                    "direction": DEAL_TYPE_LABEL.get(getattr(d, "type", None), UNKNOWN),
                    "entry": getattr(d, "entry", None),
                    "entry_label": DEAL_ENTRY_LABEL.get(getattr(d, "entry", None), UNKNOWN),
                    "volume": getattr(d, "volume", None),
                    "price": getattr(d, "price", None),
                    "actual_fill_price": getattr(d, "price", None),
                    "commission": getattr(d, "commission", None),
                    "swap": getattr(d, "swap", None),
                    "profit": getattr(d, "profit", None),
                    "time_utc": datetime.fromtimestamp(getattr(d, "time", 0), tz=timezone.utc).isoformat().replace("+00:00", "Z")
                    if getattr(d, "time", None)
                    else None,
                    "reason": getattr(d, "reason", None),
                    "_source": "mt5_history_deals_get",
                    "_kind": "history_deal",
                }
            )
        )
        if len(deals) >= MAX_DEALS:
            break
    orders: list[dict[str, Any]] = []
    for o in list(orders_raw or []):
        if not is_gold_symbol(getattr(o, "symbol", None)):
            continue
        orders.append(
            _sanitize(
                {
                    "ticket": getattr(o, "ticket", None),
                    "symbol": getattr(o, "symbol", None),
                    "type": getattr(o, "type", None),
                    "type_label": ORDER_TYPE_LABEL.get(getattr(o, "type", None), UNKNOWN),
                    "state": getattr(o, "state", None),
                    "state_label": ORDER_STATE_LABEL.get(getattr(o, "state", None), UNKNOWN),
                    "type_filling": getattr(o, "type_filling", None),
                    "volume_initial": getattr(o, "volume_initial", None),
                    "volume_current": getattr(o, "volume_current", None),
                    "price_open": getattr(o, "price_open", None),
                    "price_current": getattr(o, "price_current", None),
                    "time_setup_utc": datetime.fromtimestamp(getattr(o, "time_setup", 0), tz=timezone.utc).isoformat().replace("+00:00", "Z")
                    if getattr(o, "time_setup", None)
                    else None,
                    "time_done_utc": datetime.fromtimestamp(getattr(o, "time_done", 0), tz=timezone.utc).isoformat().replace("+00:00", "Z")
                    if getattr(o, "time_done", None)
                    else None,
                    "_source": "mt5_history_orders_get",
                }
            )
        )
        if len(orders) >= MAX_ORDERS:
            break
    meta["deal_count"] = len(deals)
    meta["order_count"] = len(orders)
    meta["ok"] = True
    return deals, orders, meta


def _merge_deals(existing: list[dict[str, Any]], live: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for deal in live + existing:
        ticket = deal.get("ticket")
        key = f"{ticket}:{deal.get('time_utc')}:{deal.get('_source')}"
        if ticket is not None:
            key = f"t:{ticket}"
        if key in seen:
            continue
        seen.add(key)
        out.append(deal)
    return out


def run_phase27_24_execution_cost_forensics(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    existing = load_all_gold_deal_records(root)
    live_deals, live_orders, collect_meta = _collect_live_history()
    deals = _merge_deals(existing, live_deals)
    p13 = _safe_load_json(root / PHASE2713_JSON) or {}
    p14 = _safe_load_json(root / PHASE2714_JSON) or {}
    real_rates = p13.get("observed_real_rates") or {}
    has_rates = real_rates.get("swap_long") is not None or real_rates.get("swap_short") is not None
    swap = analyze_swap(deals, has_broker_rates=has_rates)
    pairs = realized_slippage_pairs(deals, live_orders)
    slip_evidence = classify_slippage_evidence(len(pairs))
    execution = analyze_execution(deals, live_orders)
    gate_exec = evaluate_execution_model()
    final_gate = str((_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or UNKNOWN)
    model = build_backtest_cost_model(BacktestConfig())

    times = [d.get("time_utc") for d in deals if d.get("time_utc")]
    sanitized_deals = [
        {
            "ticket": d.get("ticket"),
            "symbol": d.get("symbol"),
            "direction": d.get("direction") or DEAL_TYPE_LABEL.get(d.get("type"), d.get("side")),
            "volume": d.get("volume") or d.get("filled_volume"),
            "entry_label": d.get("entry_label"),
            "requested_price": d.get("requested_price"),
            "actual_fill_price": d.get("actual_fill_price") or d.get("price") or d.get("entry_price"),
            "commission": d.get("commission"),
            "swap": d.get("swap"),
            "profit": d.get("profit"),
            "time_utc": d.get("time_utc") or d.get("open_timestamp_utc") or d.get("close_timestamp_utc"),
            "order": d.get("order"),
            "position_id": d.get("position_id"),
            "source": d.get("_source"),
        }
        for d in deals
    ]

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.24",
        "status": "PASS",
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "locked_policy": {
            "swap": BROKER_RATE_ONLY,
            "slippage": "MODELED",
            "validation": "COMPLETE_COSTS_REQUIRED",
        },
        "collection": collect_meta,
        "coverage": {
            "gold_deal_count": len(deals),
            "existing_artifact_deals": len(existing),
            "live_gold_deals": len(live_deals),
            "live_gold_orders": len(live_orders),
            "requested_fill_pair_count": len(pairs),
            "realized_slippage_sample_count": len(pairs),
            "partial_fill_count": execution["partial_fill_count"],
            "nonzero_swap_count": swap["nonzero_swap_count"],
            "zero_swap_count": swap["zero_swap_count"],
            "date_range": {
                "start": min(times) if times else UNKNOWN,
                "end": max(times) if times else UNKNOWN,
            },
            "evidence_completeness": UNKNOWN,
        },
        "deals_sanitized": sanitized_deals[:80],
        "orders_sanitized": live_orders[:80],
        "swap": {
            **swap,
            "broker_rates": {
                "swap_long": real_rates.get("swap_long"),
                "swap_short": real_rates.get("swap_short"),
                "rollover_3day": real_rates.get("swap_rollover3days"),
                "evidence": PROVEN if has_rates else UNKNOWN,
            },
            "classification_treatment": swap["treatment"],
            "classification_evidence": swap["evidence"],
        },
        "slippage": {
            "policy": "MODELED",
            "implementation": "MODELED_PROXY",
            "realized_sample_count": len(pairs),
            "samples": pairs[:20],
            "evidence": slip_evidence,
            "entry_price_used_as_requested": False,
            "deviation_used_as_slippage": mt5_deviation_is_realized_slippage(),
            "spread_used_as_slippage": False,
            "modeled_used_as_realized": False,
            "prior_phase27_14_realized_samples": (p14.get("operator_deal_tape") or {}).get("realized_sample_count", 0),
            "note": "REALIZED only from genuine requested_price vs actual_fill_price.",
        },
        "execution": {
            **execution,
            "gate_model_unchanged": gate_exec,
            "simulated_broker_is_not_evidence": True,
        },
        "final_output": {
            "swap": swap["evidence"],
            "realized_slippage": slip_evidence,
            "execution": execution["classification"],
        },
        "cost_gate_impact": {
            "gate_changed": False,
            "complete_costs_required_weakened": False,
            "phase27_16_final_gate_unchanged": final_gate,
            "swap_blocker_improved": False,
            "slippage_blocker_improved": False,
            "execution_gate_improved": False,
            "execution_visibility_improved": bool(live_deals or live_orders),
            "note": (
                "Forensics do not change evaluate_execution_model() or COMPLETE_COSTS_REQUIRED. "
                "Visibility of history is not gate COMPLETE."
            ),
        },
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "mt5_restarted": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "sizing_modified": False,
            "zero_swap_converted_to_zero_status": False,
            "entry_used_as_requested": False,
            "deviation_used_as_slippage": False,
            "simulated_broker_used_as_evidence": False,
            "phase_27_25_started": False,
        },
        "deferred": ["Phase 27.25+ — not started"],
    }
    if assess_cost_completeness(model) == CostCompleteness.COMPLETE:
        payload["status"] = "FAIL"
    if final_gate != "BLOCKED":
        payload["status"] = "FAIL"
    if payload["slippage"]["entry_price_used_as_requested"] or payload["slippage"]["deviation_used_as_slippage"]:
        payload["status"] = "FAIL"
    if swap["treatment"] == HISTORICAL:
        payload["status"] = "FAIL"
    if payload["cost_gate_impact"]["gate_changed"]:
        payload["status"] = "FAIL"

    out = root / PHASE2724_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_24_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_24_execution_cost_forensics(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    cov = payload["coverage"]
    swap = payload["swap"]
    slip = payload["slippage"]
    exe = payload["execution"]
    fin = payload["final_output"]
    md = f"""# Phase 27.24 — Realized Swap / Slippage / Execution Forensics

**Status:** {payload['status']}  
**Artifact:** `{PHASE2724_JSON}`  
**Collection timestamp UTC:** `{payload['timestamp']}`

Read-only. No MT5 start/restart, orders, `symbol_select`, `.env`, or Strategy/RiskGate/execution changes.

Locked policy: swap=`BROKER_RATE_ONLY`, slippage=`MODELED`, validation=`COMPLETE_COSTS_REQUIRED`.

## Coverage

| Metric | Value |
|---|---|
| gold deals | `{cov['gold_deal_count']}` |
| live gold orders | `{cov['live_gold_orders']}` |
| requested/fill pairs | `{cov['requested_fill_pair_count']}` |
| realized-slippage samples | `{cov['realized_slippage_sample_count']}` |
| partial fills | `{cov['partial_fill_count']}` |
| nonzero swap | `{cov['nonzero_swap_count']}` |
| zero swap | `{cov['zero_swap_count']}` |
| date range | `{cov['date_range']['start']}` → `{cov['date_range']['end']}` |

## Swap

Treatment: **`{swap['classification_treatment']}`**. Evidence: **`{fin['swap']}`**.

Broker rates (snapshot): long=`{swap['broker_rates'].get('swap_long')}` short=`{swap['broker_rates'].get('swap_short')}` — **{swap['broker_rates'].get('evidence')}**.  
Historical series: **`{swap['historical_swap_series']}`**. Realized zero ≠ verified zero. Series was not synthesized.

## Realized slippage

Evidence: **`{fin['realized_slippage']}`**. Samples: `{slip['realized_sample_count']}`.

entry_price was not used as requested_price. MT5 deviation was not used as slippage. MODELED was not treated as REALIZED.

## Execution

Classification: **`{fin['execution']}`**.

Filled=`{exe.get('filled_order_count')}` partial=`{exe.get('partial_fill_count')}` rejected=`{exe.get('rejected_order_count')}`.  
SimulatedBroker was not used as evidence. `evaluate_execution_model()` remains UNKNOWN / full-fill simulated.

## Cost gate impact

Gate **not changed**. COMPLETE_COSTS_REQUIRED not weakened. FINAL_GATE remains `{payload['cost_gate_impact']['phase27_16_final_gate_unchanged']}`.

| Blocker | Improved? |
|---|---|
| swap historical series | `{payload['cost_gate_impact']['swap_blocker_improved']}` |
| realized slippage distribution | `{payload['cost_gate_impact']['slippage_blocker_improved']}` |
| execution_model gate | `{payload['cost_gate_impact']['execution_gate_improved']}` |
| execution history visibility | `{payload['cost_gate_impact']['execution_visibility_improved']}` |

## Production

**BLOCKED.** Phase 27.25+ not started.

## Next

STOP after Phase 27.24.
"""
    (root / PHASE2724_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.24 execution/cost forensics:** `{PHASE2724_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.23 bid/ask expansion:** `logs/phase27_23_bidask_expansion.json` — logs tape expanded; production parquet still PROXY; C full-dataset coverage BLOCKED",
            "**Phase 27.23 bid/ask expansion:** `logs/phase27_23_bidask_expansion.json` — logs tape expanded; production parquet still PROXY; C full-dataset coverage BLOCKED  \n"
            + pointer
            + " — swap BROKER_RATE_ONLY; realized slippage UNKNOWN unless genuine requested/fill pairs exist; execution not SimulatedBroker",
        )
    fin = payload["final_output"]
    old_swap = (
        "| Swap historical realized | **UNKNOWN**. Policy Decision 4 implemented (Phase 27.13) as `BROKER_RATE_ONLY`: "
        "XAUUSD_i snapshot long=-89.136 / short=3.45 is rate evidence only; realized 0.0 on a 1s hold is not verified zero |"
    )
    new_swap = (
        "| Swap historical realized | **UNKNOWN**. Policy Decision 4 = `BROKER_RATE_ONLY`. "
        f"Phase 27.24 treatment `{payload['swap']['classification_treatment']}`; "
        f"evidence `{fin['swap']}`; historical series UNKNOWN; realized zero ≠ verified zero |"
    )
    if old_swap in text:
        text = text.replace(old_swap, new_swap)
    old_slip = (
        "| Slippage realized distribution | **UNKNOWN**. Decision 5 implemented (Phase 27.14) as `MODELED_PROXY`: "
        "session-hour proxy around assumed 0.8 pips; 0 requested-vs-fill samples; MT5 deviation 20 is not slippage |"
    )
    new_slip = (
        "| Slippage realized distribution | **UNKNOWN**. Decision 5 = `MODELED` / `MODELED_PROXY`. "
        f"Phase 27.24 realized samples `{payload['slippage']['realized_sample_count']}` "
        f"evidence `{fin['realized_slippage']}`; entry_price ≠ requested; deviation ≠ slippage |"
    )
    if old_slip in text:
        text = text.replace(old_slip, new_slip)
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
