"""Phase 27.5 — bounded read-only MT5 operator evidence (Demo/Real attach-only).

ONE attach attempt. No symbol_select, no orders, no terminal startup, no credentials.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.mt5_readonly_evidence import (
    FORBIDDEN_OUTPUT_KEYS,
    collect_historical_ticks,
    collect_readonly_deals_sample,
    collect_readonly_symbol_catalog,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE27_5_REAL_JSON = "logs/phase27_5_real_operator_evidence_raw.json"
PHASE27_5_SESSION_JSON = "logs/phase27_5_operator_session_raw.json"
PHASE27_5_TICK_META_JSON = "logs/phase27_5_bidask_tape_meta.json"
BOUNDED_ATTACH_RETRIES = 1
OPERATOR_BLOCKER = "MT5_OPERATOR_SESSION_REQUIRED"
SYMBOLS = ("XAUUSD", "XAUUSD_i")


@dataclass
class Phase275OperatorSession:
    status: str = "BLOCKED_PENDING_OPERATOR"
    operator_blocked: bool = True
    operator_blocker: str = OPERATOR_BLOCKER
    mt5_available: bool = False
    mt5_started_by_script: bool = False
    symbol_select_called: bool = False
    orders_sent: bool = False
    collection_utc: str = ""
    account: dict[str, Any] = field(default_factory=dict)
    terminal: dict[str, Any] = field(default_factory=dict)
    account_environment: str = ""
    broker: str = ""
    server: str = ""
    currency: str = ""
    symbol_catalog: dict[str, Any] = field(default_factory=dict)
    symbol_specs: dict[str, Any] = field(default_factory=dict)
    deals_sample: list[dict[str, Any]] = field(default_factory=list)
    orders_sample: list[dict[str, Any]] = field(default_factory=list)
    gold_deals: list[dict[str, Any]] = field(default_factory=list)
    gold_orders: list[dict[str, Any]] = field(default_factory=list)
    bidask_tape: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    attach_attempt: dict[str, Any] = field(default_factory=dict)
    method: str = "read-only attach-only; no symbol_select; no orders; no terminal startup"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def _account_snapshot() -> dict[str, Any]:
    try:
        import MetaTrader5 as mt5

        acct = mt5.account_info()
        if acct is None:
            return {}
        trade_mode = getattr(acct, "trade_mode", None)
        env = "REAL" if trade_mode == 2 else "DEMO"
        return _sanitize(
            {
                "type": env,
                "server": str(getattr(acct, "server", "") or ""),
                "currency": str(getattr(acct, "currency", "") or ""),
                "balance": float(getattr(acct, "balance", 0) or 0),
                "equity": float(getattr(acct, "equity", 0) or 0),
                "leverage": int(getattr(acct, "leverage", 0) or 0),
                "trade_mode": trade_mode,
            }
        )
    except Exception:
        return {}


def _terminal_snapshot() -> dict[str, Any]:
    try:
        import MetaTrader5 as mt5

        info = mt5.terminal_info()
        if info is None:
            return {}
        return _sanitize(
            {
                "build": getattr(info, "build", None),
                "connected": bool(getattr(info, "connected", False)),
                "trade_allowed": getattr(info, "trade_allowed", None),
                "community_account": getattr(info, "community_account", None),
                "snapshot_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
        )
    except Exception:
        return {}


def _collect_orders_sample(*, days: int = 90, max_orders: int = 100) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {
        "method": "history_orders_get read-only",
        "collection_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "ok": False,
    }
    try:
        import MetaTrader5 as mt5
        from datetime import timedelta

        from tradingbot.adapters.mt5_utils import ensure_mt5_connected

        if not ensure_mt5_connected({"MT5_RETRIES": BOUNDED_ATTACH_RETRIES}, attach_only=True):
            meta["error"] = "MT5 not connected"
            return [], meta

        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(days=days)
        orders = mt5.history_orders_get(date_from, date_to)
        if orders is None:
            meta["error"] = "no orders returned"
            return [], meta

        rows: list[dict[str, Any]] = []
        for o in list(orders)[-max_orders:]:
            rows.append(
                _sanitize(
                    {
                        "ticket": getattr(o, "ticket", None),
                        "symbol": getattr(o, "symbol", None),
                        "type": getattr(o, "type", None),
                        "volume_initial": getattr(o, "volume_initial", None),
                        "volume_current": getattr(o, "volume_current", None),
                        "price_open": getattr(o, "price_open", None),
                        "price_current": getattr(o, "price_current", None),
                        "sl": getattr(o, "sl", None),
                        "tp": getattr(o, "tp", None),
                        "time_setup_utc": datetime.fromtimestamp(getattr(o, "time_setup", 0), tz=timezone.utc).isoformat()
                        if getattr(o, "time_setup", None)
                        else None,
                    }
                )
            )
        meta["ok"] = True
        meta["order_count"] = len(rows)
        return rows, meta
    except ImportError:
        meta["error"] = "MetaTrader5 not installed"
        return [], meta
    except Exception as exc:
        meta["error"] = str(exc)
        return [], meta


def _filter_gold(rows: list[dict[str, Any]], *, key: str = "symbol") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get(key) or "").upper()
        if sym in ("XAUUSD", "XAUUSD_I", PRIMARY_SYMBOL.upper()):
            out.append(r)
    return out


def _probe_bidask_tape(symbol: str = PRIMARY_SYMBOL, *, days: int = 3) -> dict[str, Any]:
    """Read-only tick probe — does not modify production datasets."""
    meta: dict[str, Any] = {
        "symbol": symbol,
        "method": "copy_ticks_range read-only probe",
        "feasible": False,
        "collection_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    bounded = {"MT5_RETRIES": BOUNDED_ATTACH_RETRIES, "mt5_retries": BOUNDED_ATTACH_RETRIES}
    ticks_df, tick_meta = collect_historical_ticks(symbol, days=days, legacy_config=bounded)
    meta.update(tick_meta)
    if ticks_df is not None and not ticks_df.empty:
        meta["feasible"] = True
        meta["row_count"] = len(ticks_df)
        meta["columns"] = list(ticks_df.columns)
        staging = Path("logs/phase27_5_bidask_tape_staging.parquet")
        staging.parent.mkdir(parents=True, exist_ok=True)
        ticks_df.to_parquet(staging, index=False)
        meta["staging_path"] = str(staging)
        meta["note"] = "evidence-only staging artifact; not ingested into production backtest datasets"
    else:
        meta["blocker"] = tick_meta.get("error", "no ticks")
    return meta


def collect_phase27_5_operator_session(
    base_dir: str | Path | None = None,
    *,
    deal_days: int = 90,
    tick_days: int = 3,
) -> Phase275OperatorSession:
    """ONE bounded read-only attach — collects whatever terminal is connected (Demo or Real)."""
    root = Path(base_dir or Path.cwd())
    result = Phase275OperatorSession(
        collection_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )

    bounded_config = {"MT5_RETRIES": BOUNDED_ATTACH_RETRIES, "mt5_retries": BOUNDED_ATTACH_RETRIES}
    catalog = collect_readonly_symbol_catalog(SYMBOLS, legacy_config=bounded_config)

    if not catalog.ok:
        result.attach_attempt = {
            "attempt_utc": result.collection_utc,
            "retry_count": BOUNDED_ATTACH_RETRIES,
            "attach_only": True,
            "mt5_started_by_script": False,
            "symbol_select_called": False,
            "exact_error": catalog.errors[0] if catalog.errors else "MT5 not connected",
            "method": result.method,
        }
        result.errors.extend(catalog.errors)
        _write_artifacts(root, result)
        return result

    result.mt5_available = True
    result.operator_blocked = False
    result.operator_blocker = ""
    result.status = "COLLECTED"
    result.account = _account_snapshot()
    result.terminal = _terminal_snapshot()
    result.account_environment = result.account.get("type") or catalog.account_environment
    result.server = result.account.get("server") or catalog.server
    result.currency = result.account.get("currency") or catalog.currency
    result.broker = "LiteFinance" if "LiteFinance" in (result.server or "") else (result.server or "")
    result.symbol_catalog = dict(catalog.catalog)
    result.symbol_specs = dict(catalog.symbol_specs)
    result.attach_attempt = {
        "attempt_utc": catalog.collection_utc,
        "retry_count": BOUNDED_ATTACH_RETRIES,
        "attach_only": True,
        "mt5_started_by_script": False,
        "symbol_select_called": False,
        "exact_error": None,
        "method": "single bounded read-only attach succeeded",
    }

    deals, deal_meta = collect_readonly_deals_sample(days=deal_days, legacy_config=bounded_config)
    result.deals_sample = _sanitize(deals)
    result.gold_deals = _filter_gold(result.deals_sample)
    if deal_meta.get("error"):
        result.errors.append(str(deal_meta["error"]))

    orders, order_meta = _collect_orders_sample(days=deal_days)
    result.orders_sample = _sanitize(orders)
    result.gold_orders = _filter_gold(result.orders_sample)
    if order_meta.get("error") and order_meta.get("error") != "no orders returned":
        result.errors.append(str(order_meta.get("error")))

    if result.account_environment == "REAL":
        result.bidask_tape = _probe_bidask_tape(tick_days=tick_days)
    else:
        result.bidask_tape = {
            "feasible": False,
            "blocker": "REAL terminal not attached — bid-ask tape deferred to Real session",
            "demo_attached": True,
        }

    _write_artifacts(root, result)
    return result


def _write_artifacts(root: Path, result: Phase275OperatorSession) -> None:
    payload = _sanitize(result.to_dict())
    session_path = root / PHASE27_5_SESSION_JSON
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if result.account_environment == "REAL" and result.mt5_available:
        real_path = root / PHASE27_5_REAL_JSON
        real_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if result.bidask_tape.get("feasible"):
        meta_path = root / PHASE27_5_TICK_META_JSON
        meta_path.write_text(json.dumps(result.bidask_tape, indent=2, sort_keys=True), encoding="utf-8")


def run_phase27_5_operator_collection(base_dir: str | Path | None = None) -> Phase275OperatorSession:
    return collect_phase27_5_operator_session(base_dir)
