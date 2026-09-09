"""Phase 27 — single bounded read-only operator evidence collection path.

Attach-only MT5 inspection. No symbol_select, no orders, no terminal startup, no credentials.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.mt5_readonly_evidence import (
    FORBIDDEN_OUTPUT_KEYS,
    collect_readonly_deals_sample,
    collect_readonly_symbol_catalog,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE27_OPERATOR_JSON = "logs/phase27_operator_evidence_raw.json"
BOUNDED_ATTACH_RETRIES = 1
OPERATOR_BLOCKER = "MT5_OPERATOR_SESSION_REQUIRED"
SYMBOLS = ("XAUUSD", "XAUUSD_i")


@dataclass
class Phase27OperatorResult:
    status: str = "BLOCKED_PENDING_OPERATOR"
    operator_blocked: bool = True
    operator_blocker: str = OPERATOR_BLOCKER
    mt5_available: bool = False
    mt5_started_by_script: bool = False
    symbol_select_called: bool = False
    orders_sent: bool = False
    collection_utc: str = ""
    account_type: str = ""
    broker: str = ""
    server: str = ""
    terminal_build: str = ""
    currency: str = ""
    symbol_catalog: dict[str, Any] = field(default_factory=dict)
    symbol_specs: dict[str, Any] = field(default_factory=dict)
    deals_sample: list[dict[str, Any]] = field(default_factory=list)
    gold_deals: list[dict[str, Any]] = field(default_factory=list)
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


def _terminal_build() -> str:
    try:
        import MetaTrader5 as mt5

        info = mt5.terminal_info()
        if info is None:
            return ""
        return str(getattr(info, "build", "") or getattr(info, "community_account", "") or "")
    except Exception:
        return ""


def _filter_gold_deals(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in deals:
        sym = str(d.get("symbol") or "").upper()
        if sym in ("XAUUSD", "XAUUSD_I", PRIMARY_SYMBOL.upper()):
            out.append(d)
    return out


def collect_phase27_operator_evidence(
    base_dir: str | Path | None = None,
    *,
    deal_days: int = 30,
) -> Phase27OperatorResult:
    """Bounded read-only operator evidence — exit quickly when MT5 unavailable."""
    root = Path(base_dir or Path.cwd())
    result = Phase27OperatorResult(
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
        _write_result(root, result)
        return result

    result.mt5_available = True
    result.operator_blocked = False
    result.operator_blocker = ""
    result.status = "COLLECTED"
    result.account_type = catalog.account_environment
    result.server = catalog.server
    result.currency = catalog.currency
    result.broker = "LiteFinance" if "LiteFinance" in (catalog.server or "") else (catalog.server or "")
    result.terminal_build = _terminal_build()
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
    result.gold_deals = _filter_gold_deals(result.deals_sample)
    if deal_meta.get("error"):
        result.errors.append(str(deal_meta["error"]))

    _write_result(root, result)
    return result


def _write_result(root: Path, result: Phase27OperatorResult) -> Path:
    out = root / PHASE27_OPERATOR_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = _sanitize(result.to_dict())
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def run_phase27_operator_evidence_collection(base_dir: str | Path | None = None) -> Phase27OperatorResult:
    """Phase 27 operator entry point — delegates to bounded read-only collector."""
    return collect_phase27_operator_evidence(base_dir)
