"""Phase 10.2 — MT5 live preflight audit (read-only)."""

from __future__ import annotations

import ast
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.ml.data.paths import ml_live_preflight_report_path

logger = logging.getLogger(__name__)

FORBIDDEN_AST = (
    "order_send",
    "trade_request",
    "positions_get",
    "mt5_execution",
    "live_order",
    "tradingbot.adapters.mt5_execution",
)

LIVE_PKG_FILES = (
    "live_market_adapter.py",
    "live_shadow_runner.py",
    "live_preflight.py",
    "live_run_logger.py",
    "live_metrics.py",
    "sl_tp_calculator.py",
    "trade_integrity.py",
    "virtual_trade_builder.py",
    "trade_integrity_logger.py",
)


def scan_live_shadow_ast(integration_root: Path | None = None) -> list[str]:
    root = integration_root or Path(__file__).resolve().parent
    violations: list[str] = []
    for name in LIVE_PKG_FILES:
        path = root / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Call):
                func = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if func in ("order_send", "positions_get"):
                    violations.append(f"{name}: call {func}")
                continue
            else:
                continue
            for module in mods:
                for prefix in FORBIDDEN_AST:
                    if prefix in module or module == prefix:
                        violations.append(f"{name}: {module}")
    return violations


def run_live_preflight(
    symbol: str,
    timeframe: str,
    *,
    config: dict[str, Any] | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Verify MT5 read-only connectivity before live shadow run."""
    cfg = dict(config or load_legacy_config())
    symbol = symbol.upper()
    timeframe = timeframe.upper()
    now = datetime.now(timezone.utc).isoformat()

    report: dict[str, Any] = {
        "phase": "10.2",
        "timestamp_utc": now,
        "symbol": symbol,
        "broker_symbol": symbol,
        "timeframe": timeframe,
        "mt5_status": "unknown",
        "connection_ok": False,
        "symbol_available": False,
        "copy_rates_ok": False,
        "symbol_info_tick_ok": False,
        "spread_available": False,
        "account_readonly": {},
        "ast_violations": scan_live_shadow_ast(),
        "forbidden_calls_blocked": True,
    }

    try:
        import MetaTrader5 as mt5
    except ImportError:
        report["mt5_status"] = "MetaTrader5 package not installed"
        _save(report, base_dir)
        return report

    from tradingbot.adapters.mt5_utils import ensure_mt5_connected

    connected = ensure_mt5_connected(cfg, symbols=[symbol], strict_account=False)
    report["connection_ok"] = bool(connected)
    report["mt5_status"] = "connected" if connected else "disconnected"

    if not connected:
        _save(report, base_dir)
        return report

    broker = resolve_broker_symbol(symbol, cfg)
    report["broker_symbol"] = broker

    info = mt5.symbol_info(broker)
    report["symbol_available"] = info is not None and bool(getattr(info, "visible", True))
    if info is not None:
        report["symbol_info"] = {
            "point": float(getattr(info, "point", 0)),
            "digits": int(getattr(info, "digits", 0)),
            "trade_mode": int(getattr(info, "trade_mode", 0)),
        }

    legacy_tf = to_legacy(timeframe)
    tf_map = {"5m": "TIMEFRAME_M5", "m5": "TIMEFRAME_M5"}
    tf_const = getattr(mt5, tf_map.get(legacy_tf.lower(), "TIMEFRAME_M5"))
    rates = mt5.copy_rates_from_pos(broker, tf_const, 0, 10)
    report["copy_rates_ok"] = rates is not None and len(rates) > 0

    tick = mt5.symbol_info_tick(broker)
    report["symbol_info_tick_ok"] = tick is not None
    if tick is not None:
        from tradingbot.domain.session_logic import spread_pips_from_prices

        spread = spread_pips_from_prices(float(tick.ask), float(tick.bid), symbol)
        report["spread_pips"] = round(spread, 4)
        report["spread_available"] = spread < 900.0

    acct = mt5.account_info()
    if acct is not None:
        report["account_readonly"] = {
            "login": int(acct.login),
            "balance": float(acct.balance),
            "equity": float(acct.equity),
            "server": str(acct.server),
        }

    report["preflight_pass"] = (
        report["connection_ok"]
        and report["symbol_available"]
        and report["copy_rates_ok"]
        and report["symbol_info_tick_ok"]
        and len(report["ast_violations"]) == 0
    )
    _save(report, base_dir)
    return report


def _save(report: dict[str, Any], base_dir: str | Path | None) -> None:
    path = ml_live_preflight_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Live preflight report -> %s", path)
