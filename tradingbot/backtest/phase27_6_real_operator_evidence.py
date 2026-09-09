"""Phase 27.6 — bounded REAL-terminal read-only evidence (ONE attach attempt).

If connected terminal is Demo, Real evidence is BLOCKED — not mislabeled as Real.
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

PHASE276_REAL_JSON = "logs/phase27_6_real_operator_evidence_raw.json"
PHASE276_SESSION_JSON = "logs/phase27_6_operator_session_raw.json"
PHASE276_TICK_META_JSON = "logs/phase27_6_bidask_tape_meta.json"
BOUNDED_ATTACH_RETRIES = 1
REAL_OPERATOR_BLOCKER = "REAL_MT5_OPERATOR_SESSION_REQUIRED"
SYMBOLS = ("XAUUSD", "XAUUSD_i")


@dataclass
class Phase276RealEvidenceResult:
    status: str = "BLOCKED_PENDING_OPERATOR"
    real_operator_evidence: str = "BLOCKED_PENDING_OPERATOR"
    operator_blocked: bool = True
    operator_blocker: str = REAL_OPERATOR_BLOCKER
    mt5_available: bool = False
    is_real_terminal: bool = False
    is_demo_terminal: bool = False
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
                "snapshot_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
        )
    except Exception:
        return {}


def _collect_orders_sample(*, days: int = 180, max_orders: int = 200) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {"method": "history_orders_get read-only", "ok": False}
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
        rows = [
            _sanitize(
                {
                    "ticket": getattr(o, "ticket", None),
                    "symbol": getattr(o, "symbol", None),
                    "type": getattr(o, "type", None),
                    "volume_initial": getattr(o, "volume_initial", None),
                    "volume_current": getattr(o, "volume_current", None),
                    "price_open": getattr(o, "price_open", None),
                    "time_setup_utc": datetime.fromtimestamp(getattr(o, "time_setup", 0), tz=timezone.utc).isoformat()
                    if getattr(o, "time_setup", None)
                    else None,
                }
            )
            for o in list(orders)[-max_orders:]
        ]
        meta["ok"] = True
        meta["order_count"] = len(rows)
        return rows, meta
    except ImportError:
        meta["error"] = "MetaTrader5 not installed"
        return [], meta
    except Exception as exc:
        meta["error"] = str(exc)
        return [], meta


def _filter_gold(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("symbol") or "").upper() in ("XAUUSD", "XAUUSD_I", PRIMARY_SYMBOL.upper())]


def _probe_tape(symbol: str = PRIMARY_SYMBOL, *, days: int = 7) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "symbol": symbol,
        "method": "copy_ticks_range read-only",
        "feasible": False,
        "collection_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    bounded = {"MT5_RETRIES": BOUNDED_ATTACH_RETRIES, "mt5_retries": BOUNDED_ATTACH_RETRIES}
    ticks_df, tick_meta = collect_historical_ticks(symbol, days=days, legacy_config=bounded)
    meta.update({k: v for k, v in tick_meta.items() if k != "error"})
    if ticks_df is not None and not ticks_df.empty:
        meta["feasible"] = True
        meta["row_count"] = len(ticks_df)
        staging = Path("logs/phase27_6_bidask_tape_staging.parquet")
        staging.parent.mkdir(parents=True, exist_ok=True)
        ticks_df.to_parquet(staging, index=False)
        meta["staging_path"] = str(staging)
        meta["note"] = "evidence-only; not ingested into production backtest datasets"
    else:
        meta["blocker"] = tick_meta.get("error", "no ticks")
    return meta


def attempt_real_operator_evidence(base_dir: str | Path | None = None) -> Phase276RealEvidenceResult:
    """ONE bounded attach. Real evidence only when account_info confirms REAL."""
    root = Path(base_dir or Path.cwd())
    result = Phase276RealEvidenceResult(
        collection_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    bounded = {"MT5_RETRIES": BOUNDED_ATTACH_RETRIES, "mt5_retries": BOUNDED_ATTACH_RETRIES}
    catalog = collect_readonly_symbol_catalog(SYMBOLS, legacy_config=bounded)

    if not catalog.ok:
        result.attach_attempt = {
            "attempt_utc": result.collection_utc,
            "retry_count": BOUNDED_ATTACH_RETRIES,
            "attach_only": True,
            "exact_error": catalog.errors[0] if catalog.errors else "MT5 not connected",
        }
        result.errors.extend(catalog.errors)
        _write(root, result)
        return result

    result.mt5_available = True
    result.account = _account_snapshot()
    result.terminal = _terminal_snapshot()
    env = str(result.account.get("type") or catalog.account_environment or "").upper()
    result.account_environment = env
    result.is_real_terminal = env == "REAL"
    result.is_demo_terminal = env == "DEMO"
    result.server = str(result.account.get("server") or catalog.server or "")
    result.currency = str(result.account.get("currency") or catalog.currency or "")
    result.broker = "LiteFinance" if "LiteFinance" in result.server else result.server
    result.symbol_catalog = dict(catalog.catalog)
    result.symbol_specs = dict(catalog.symbol_specs)
    result.attach_attempt = {
        "attempt_utc": catalog.collection_utc,
        "retry_count": BOUNDED_ATTACH_RETRIES,
        "attach_only": True,
        "environment_detected": env,
    }

    deals, deal_meta = collect_readonly_deals_sample(days=180, legacy_config=bounded)
    result.deals_sample = _sanitize(deals)
    result.gold_deals = _filter_gold(result.deals_sample)
    orders, order_meta = _collect_orders_sample()
    result.orders_sample = _sanitize(orders)
    result.gold_orders = _filter_gold(result.orders_sample)

    if not result.is_real_terminal:
        result.real_operator_evidence = "BLOCKED_PENDING_OPERATOR"
        result.operator_blocked = True
        result.operator_blocker = REAL_OPERATOR_BLOCKER
        result.status = "DEMO_ATTACHED_NOT_REAL"
        result.errors.append(f"Connected terminal is {env}, not REAL — Real evidence not collected")
        result.bidask_tape = {"feasible": False, "blocker": "REAL terminal required for Real-bound tape"}
        _write(root, result)
        return result

    result.real_operator_evidence = "COLLECTED"
    result.operator_blocked = False
    result.operator_blocker = ""
    result.status = "REAL_COLLECTED"
    result.bidask_tape = _probe_tape()
    _write(root, result)
    return result


def _write(root: Path, result: Phase276RealEvidenceResult) -> None:
    payload = _sanitize(result.to_dict())
    (root / PHASE276_SESSION_JSON).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if result.is_real_terminal and result.real_operator_evidence == "COLLECTED":
        (root / PHASE276_REAL_JSON).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if result.bidask_tape.get("feasible"):
        (root / PHASE276_TICK_META_JSON).write_text(
            json.dumps(result.bidask_tape, indent=2, sort_keys=True), encoding="utf-8"
        )


def run_phase27_6_real_operator_collection(base_dir: str | Path | None = None) -> Phase276RealEvidenceResult:
    return attempt_real_operator_evidence(base_dir)
