"""Read-only MT5 evidence collection — no orders, no symbol_select, no credentials in output."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

FORBIDDEN_OUTPUT_KEYS = frozenset(
    {"login", "password", "mt5_password", "mt5_login", "server_password", "token", "api_key"}
)

SPEC_KEYS: tuple[str, ...] = (
    "digits",
    "point",
    "trade_contract_size",
    "trade_tick_size",
    "trade_tick_value",
    "trade_tick_value_profit",
    "trade_tick_value_loss",
    "volume_min",
    "volume_max",
    "volume_step",
    "trade_stops_level",
    "trade_freeze_level",
    "filling_mode",
    "trade_mode",
    "trade_exemode",
    "trade_calc_mode",
    "currency_base",
    "currency_profit",
    "currency_margin",
    "swap_long",
    "swap_short",
    "swap_rollover3days",
)


@dataclass
class ReadOnlyCollectionResult:
    ok: bool
    method: str = "read-only; no symbol_select; no orders"
    collection_utc: str = ""
    account_environment: str = ""
    server: str = ""
    currency: str = ""
    errors: list[str] = field(default_factory=list)
    catalog: dict[str, Any] = field(default_factory=dict)
    symbol_specs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items() if str(k).lower() not in FORBIDDEN_OUTPUT_KEYS}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def _spec_from_symbol_info(info: Any) -> dict[str, Any]:
    if info is None:
        return {}
    out: dict[str, Any] = {}
    for key in SPEC_KEYS:
        if hasattr(info, key):
            val = getattr(info, key)
            if val is not None:
                out[key] = val
    return out


def collect_readonly_symbol_catalog(
    symbols: tuple[str, ...] = ("XAUUSD", "XAUUSD_i"),
    *,
    legacy_config: dict[str, Any] | None = None,
) -> ReadOnlyCollectionResult:
    """
    Read-only MT5 symbol catalog/spec inspection.

    Uses symbol_info and symbols_get only — never symbol_select.
    """
    result = ReadOnlyCollectionResult(
        ok=False,
        collection_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    try:
        import MetaTrader5 as mt5
    except ImportError:
        result.errors.append("MetaTrader5 package not installed")
        return result

    from tradingbot.adapters.mt5_utils import ensure_mt5_connected

    if not ensure_mt5_connected(legacy_config or {}, attach_only=True):
        result.errors.append("MT5 not connected")
        return result

    account = mt5.account_info()
    if account is not None:
        trade_mode = getattr(account, "trade_mode", None)
        env = "REAL" if trade_mode == 2 else "DEMO"
        result.account_environment = env
        result.server = str(getattr(account, "server", "") or "")
        result.currency = str(getattr(account, "currency", "") or "")

    catalog_names = set()
    try:
        all_symbols = mt5.symbols_get()
        if all_symbols:
            catalog_names = {str(s.name) for s in all_symbols}
    except Exception as exc:
        result.errors.append(f"symbols_get failed: {exc}")

    result.catalog = {
        "total_symbols": len(catalog_names),
        "exact_matches": {sym: ("YES" if sym in catalog_names else "NO") for sym in symbols},
    }

    for sym in symbols:
        info = mt5.symbol_info(sym)
        exists = info is not None
        entry: dict[str, Any] = {
            "symbol": sym,
            "exists": exists,
            "in_symbols_get": sym in catalog_names,
        }
        if exists:
            entry["visible"] = bool(getattr(info, "visible", False))
            entry["selected"] = bool(getattr(info, "select", False))
            entry["spec"] = _spec_from_symbol_info(info)
            tick = mt5.symbol_info_tick(sym)
            if tick is not None:
                entry["quote"] = {
                    "bid": float(tick.bid),
                    "ask": float(tick.ask),
                    "spread_price_units": float(tick.ask - tick.bid),
                    "time_utc": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
                }
        else:
            entry["all_fields"] = "NOT AVAILABLE — symbol not found"
        result.symbol_specs[sym] = entry

    result.ok = True
    return result


def collect_historical_ticks(
    symbol: str,
    *,
    days: int = 7,
    max_ticks: int = 500_000,
    legacy_config: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """
    Read-only historical tick collection via copy_ticks_range.

    No symbol_select. Returns None if symbol unavailable or collection fails.
    """
    meta: dict[str, Any] = {
        "symbol": symbol,
        "method": "copy_ticks_range read-only",
        "collection_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "ok": False,
    }
    try:
        import MetaTrader5 as mt5
    except ImportError:
        meta["error"] = "MetaTrader5 not installed"
        return None, meta

    from tradingbot.adapters.mt5_utils import ensure_mt5_connected

    if not ensure_mt5_connected(legacy_config or {}, attach_only=True):
        meta["error"] = "MT5 not connected"
        return None, meta

    info = mt5.symbol_info(symbol)
    if info is None:
        meta["error"] = f"symbol {symbol!r} not found"
        return None, meta

    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days)
    flags = mt5.COPY_TICKS_ALL
    try:
        ticks = mt5.copy_ticks_range(symbol, date_from, date_to, flags)
    except Exception as exc:
        meta["error"] = f"copy_ticks_range failed: {exc}"
        return None, meta

    if ticks is None or len(ticks) == 0:
        meta["error"] = "no ticks returned"
        return None, meta

    df = pd.DataFrame(ticks)
    if len(df) > max_ticks:
        df = df.iloc[-max_ticks:].copy()
    meta["ok"] = True
    meta["row_count"] = len(df)
    meta["date_from_utc"] = date_from.isoformat()
    meta["date_to_utc"] = date_to.isoformat()
    meta["columns"] = list(df.columns)
    return df, meta


def collect_readonly_deals_sample(
    *,
    days: int = 30,
    max_deals: int = 50,
    legacy_config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Read-only recent deal history — no orders, no credentials in output.

    Used for commission/slippage evidence assessment only; sparse samples remain UNKNOWN.
    """
    meta: dict[str, Any] = {
        "method": "history_deals_get read-only",
        "collection_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "ok": False,
    }
    try:
        import MetaTrader5 as mt5
    except ImportError:
        meta["error"] = "MetaTrader5 not installed"
        return [], meta

    from tradingbot.adapters.mt5_utils import ensure_mt5_connected

    if not ensure_mt5_connected(legacy_config or {}, attach_only=True):
        meta["error"] = "MT5 not connected"
        return [], meta

    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days)
    try:
        deals = mt5.history_deals_get(date_from, date_to)
    except Exception as exc:
        meta["error"] = f"history_deals_get failed: {exc}"
        return [], meta

    if deals is None:
        meta["error"] = "no deals returned"
        return [], meta

    rows: list[dict[str, Any]] = []
    for d in list(deals)[-max_deals:]:
        rows.append(
            _sanitize(
                {
                    "ticket": getattr(d, "ticket", None),
                    "symbol": getattr(d, "symbol", None),
                    "type": getattr(d, "type", None),
                    "volume": getattr(d, "volume", None),
                    "price": getattr(d, "price", None),
                    "commission": getattr(d, "commission", None),
                    "swap": getattr(d, "swap", None),
                    "profit": getattr(d, "profit", None),
                    "time_utc": datetime.fromtimestamp(getattr(d, "time", 0), tz=timezone.utc).isoformat()
                    if getattr(d, "time", None)
                    else None,
                }
            )
        )
    meta["ok"] = True
    meta["deal_count"] = len(rows)
    return rows, meta


def ticks_to_m5_bidask_bars(ticks: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate observed ticks to M5 bars with last-tick bid/ask per bar.

    OHLC from tick `last` when >0 else mid(bid, ask). No synthetic spread.
    """
    if ticks is None or ticks.empty:
        return pd.DataFrame()

    df = ticks.copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
    elif not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("ticks require time column or DatetimeIndex")

    df = df.sort_index()
    last = pd.to_numeric(df.get("last"), errors="coerce")
    bid = pd.to_numeric(df["bid"], errors="coerce")
    ask = pd.to_numeric(df["ask"], errors="coerce")
    price = last.where(last > 0, (bid + ask) / 2.0)

    grouped = df.resample("5min")
    bars = pd.DataFrame(
        {
            "open": price.resample("5min").first(),
            "high": price.resample("5min").max(),
            "low": price.resample("5min").min(),
            "close": price.resample("5min").last(),
            "volume": df.get("volume", pd.Series(0, index=df.index)).resample("5min").sum(),
            "bid": bid.resample("5min").last(),
            "ask": ask.resample("5min").last(),
        }
    )
    bars = bars.dropna(subset=["open", "high", "low", "close", "bid", "ask"])
    return bars


def save_readonly_evidence(result: ReadOnlyCollectionResult, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = _sanitize(result.to_dict())
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out
