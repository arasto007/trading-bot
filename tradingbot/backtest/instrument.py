"""Offline broker instrument specification for backtest — no MT5 dependency."""

from __future__ import annotations

from typing import Any

from tradingbot.domain.broker_economics import BrokerEconomics

# LiteFinance Demo/Real operator evidence (2026-09-02) for XAUUSD_i only.
# Not a universal broker default — explicit offline fallback when no catalog is configured.
# Bare XAUUSD is intentionally absent: no silent economics alias (EV-EQ-01 NOT_PROVEN).
OFFLINE_INSTRUMENT_CATALOG: dict[str, dict[str, Any]] = {
    "XAUUSD_i": {
        "exists": True,
        "point": 0.01,
        "digits": 2,
        "contract_size": 100.0,
        "tick_size": 0.01,
        "tick_value": 1.0,
        "tick_value_profit": 1.0,
        "tick_value_loss": 1.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "stops_level": 0,
        "freeze_level": 0,
        "filling_mode": 1,
        "trade_mode": 4,
    },
}


def merge_broker_catalog(legacy_config: dict[str, Any], extra: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Merge offline instrument entries into legacy BROKER_SYMBOL_CATALOG."""
    out = dict(legacy_config)
    catalog = dict(out.get("BROKER_SYMBOL_CATALOG") or {})
    for sym, entry in (extra or {}).items():
        catalog[sym] = {**catalog.get(sym, {}), **entry}
    out["BROKER_SYMBOL_CATALOG"] = catalog
    return out


def resolve_backtest_economics(
    symbol: str,
    legacy_config: dict[str, Any] | None = None,
    *,
    allow_offline_fallback: bool = True,
) -> BrokerEconomics | None:
    """
    Load BrokerEconomics for backtest sizing/validation.

    Priority:
      1. legacy_config['BROKER_SYMBOL_CATALOG'][symbol]
      2. documented OFFLINE_INSTRUMENT_CATALOG (when allow_offline_fallback)
      3. None — callers must fail closed
    """
    from tradingbot.adapters.symbols import load_broker_economics

    cfg = legacy_config or {}
    economics = load_broker_economics(symbol, cfg)
    if economics is not None:
        return economics

    if not allow_offline_fallback:
        return None

    entry = OFFLINE_INSTRUMENT_CATALOG.get(symbol)
    if entry is None:
        return None
    return BrokerEconomics.from_mapping(symbol, entry)


def default_offline_catalog_for_symbols(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Build catalog entries only for symbols with documented offline specs."""
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        if sym in OFFLINE_INSTRUMENT_CATALOG:
            out[sym] = dict(OFFLINE_INSTRUMENT_CATALOG[sym])
    return out
