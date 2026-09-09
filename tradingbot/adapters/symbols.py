"""Explicit environment-aware broker symbol resolution — no silent +/- _i hunt."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class SymbolResolutionError(Exception):
    """Configured trading symbol is missing or not tradable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_account_environment(config: dict[str, Any] | None = None) -> str:
    """Return DEMO or REAL from config or non-secret env."""
    cfg = config or {}
    raw = cfg.get("ACCOUNT_ENVIRONMENT")
    if raw is None:
        raw = os.getenv("TRADINGBOT_ACCOUNT_ENV") or os.getenv(
            "TRADINGBOT_ACCOUNT_ENVIRONMENT", "DEMO"
        )
    env = str(raw).strip().upper()
    if env in ("REAL", "LIVE"):
        return "REAL"
    return "DEMO"


def get_symbol_by_environment(config: dict[str, Any] | None = None) -> dict[str, str]:
    """Environment → broker symbol map (configuration-driven)."""
    cfg = config or {}
    mapping = cfg.get("SYMBOL_BY_ENVIRONMENT")
    if isinstance(mapping, dict) and mapping:
        return {str(k).upper(): str(v) for k, v in mapping.items()}
    from tradingbot.config.live import PRIMARY_SYMBOL, SYMBOL_BY_ENVIRONMENT

    return dict(SYMBOL_BY_ENVIRONMENT or {"DEMO": PRIMARY_SYMBOL, "REAL": PRIMARY_SYMBOL})


def get_environment_trading_symbol(config: dict[str, Any] | None = None) -> str:
    """Broker symbol for the current ACCOUNT_ENVIRONMENT."""
    env = parse_account_environment(config)
    mapping = get_symbol_by_environment(config)
    symbol = mapping.get(env) or mapping.get("DEMO")
    if not symbol:
        from tradingbot.config.live import PRIMARY_SYMBOL

        return PRIMARY_SYMBOL
    return symbol


def _test_catalog_entry(name: str, config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Offline/test hook: config['BROKER_SYMBOL_CATALOG'][name] = {...}."""
    catalog = (config or {}).get("BROKER_SYMBOL_CATALOG") or {}
    entry = catalog.get(name)
    return entry if isinstance(entry, dict) else None


def _mt5_symbol_exists(name: str, config: dict[str, Any] | None = None) -> bool:
    test_entry = _test_catalog_entry(name, config)
    if test_entry is not None:
        return bool(test_entry.get("exists", True))
    try:
        from tradingbot.adapters.legacy_loader import ensure_legacy_path

        ensure_legacy_path()
        import MetaTrader5 as mt5  # noqa: E402

        info = mt5.symbol_info(name)
        return info is not None
    except Exception as exc:
        logger.debug("MT5 symbol existence check skipped for %s: %s", name, exc)
        return False


def validate_configured_symbol(
    symbol: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Read-only validation: configured symbol must exist in broker catalog.
    Does NOT call symbol_select.
    """
    target = symbol or get_environment_trading_symbol(config)
    if not target:
        return False, "CONFIGURED_SYMBOL_EMPTY"
    if _mt5_symbol_exists(target, config):
        return True, "ok"
    return False, f"CONFIGURED_SYMBOL_MISSING:{target}"


def validate_configured_symbol_or_raise(
    symbol: str | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    target = symbol or get_environment_trading_symbol(config)
    ok, reason = validate_configured_symbol(target, config)
    if not ok:
        raise SymbolResolutionError("SYMBOL_NOT_FOUND", reason)
    return target


def resolve_broker_symbol(symbol: str, config: dict[str, Any] | None = None) -> str:
    """
    Resolve to the environment-configured broker symbol.

    No silent +/- _i hunt. No symbol_select. Explicit symbol_aliases only.
    """
    cfg = config or {}
    overrides = cfg.get("symbol_aliases") or {}
    if symbol in overrides:
        resolved = str(overrides[symbol])
    else:
        configured = get_environment_trading_symbol(cfg)
        from tradingbot.config.live import PRIMARY_SYMBOL

        canonical = symbol.upper()
        allowed = {configured.upper(), PRIMARY_SYMBOL.upper(), "XAUUSD"}
        if canonical not in allowed:
            logger.warning(
                "resolve_broker_symbol: %s not in allowed canonical set %s; using configured %s",
                symbol,
                sorted(allowed),
                configured,
            )
        resolved = configured

    strict = cfg.get("SYMBOL_RESOLUTION_STRICT", True)
    if not strict:
        return resolved

    ok, reason = validate_configured_symbol(resolved, cfg)
    if not ok:
        catalog = cfg.get("BROKER_SYMBOL_CATALOG")
        if catalog is not None:
            raise SymbolResolutionError("SYMBOL_NOT_FOUND", reason)
        logger.warning("Symbol validation failed (MT5 unavailable?): %s", reason)
    return resolved


def load_broker_economics(
    symbol: str | None = None,
    config: dict[str, Any] | None = None,
):
    """
    Load BrokerEconomics for the configured symbol (read-only symbol_info).
    Returns None if unavailable — callers must fail closed.
    """
    from tradingbot.domain.broker_economics import BrokerEconomics

    name = symbol or get_environment_trading_symbol(config)
    test_entry = _test_catalog_entry(name, config)
    if test_entry is not None:
        return BrokerEconomics.from_mapping(name, test_entry)

    try:
        from tradingbot.adapters.legacy_loader import ensure_legacy_path

        ensure_legacy_path()
        import MetaTrader5 as mt5  # noqa: E402

        info = mt5.symbol_info(name)
        return BrokerEconomics.from_mt5_symbol_info(info)
    except Exception as exc:
        logger.debug("broker economics load failed for %s: %s", name, exc)
        return None
