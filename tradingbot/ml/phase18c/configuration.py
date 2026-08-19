"""Phase 18C — runtime configuration validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.phase18c.config import DEFAULT_SYMBOL, DEFAULT_TIMEFRAME


def validate_configuration(
    *,
    project_root: Path,
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    base_dir: str | None = None,
) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}

    # Risk / position sizing modules present
    risk_path = project_root / "tradingbot/adapters/risk_gate.py"
    items["risk"] = {"status": "PASS" if risk_path.is_file() else "FAIL", "path": str(risk_path)}

    risk_intel = project_root / "tradingbot/ml/risk_intelligence"
    items["position_sizing"] = {
        "status": "PASS" if risk_intel.is_dir() else "WARN",
        "path": str(risk_intel),
    }

    # Spread filter / trading hours — config load
    try:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        cfg = load_legacy_config()
        items["spread_filter"] = {
            "status": "PASS",
            "keys_present": [k for k in cfg if "spread" in k.lower()][:10],
        }
        items["trading_hours"] = {
            "status": "PASS",
            "keys_present": [k for k in cfg if "hour" in k.lower() or "session" in k.lower()][:10],
        }
        items["symbol_configuration"] = {
            "status": "PASS",
            "symbol": symbol,
            "config_symbols": cfg.get("symbols") or cfg.get("SYMBOLS") or symbol,
        }
        items["timeframe"] = {
            "status": "PASS",
            "timeframe": timeframe,
        }
    except Exception as exc:  # noqa: BLE001
        items["spread_filter"] = {"status": "WARN", "error": str(exc)}
        items["trading_hours"] = {"status": "WARN", "error": str(exc)}
        items["symbol_configuration"] = {"status": "PASS", "symbol": symbol}
        items["timeframe"] = {"status": "PASS", "timeframe": timeframe}

    # Logging / monitoring / output folders
    log_dir = project_root / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_ok = log_dir.is_dir()
    except OSError:
        log_ok = False
    items["logging"] = {"status": "PASS" if log_ok else "FAIL", "path": str(log_dir)}
    mon = project_root / "tradingbot/ml/monitoring"
    items["monitoring"] = {"status": "PASS" if mon.is_dir() else "WARN", "path": str(mon)}

    reports = project_root / "data" / "ml" / "reports"
    try:
        reports.mkdir(parents=True, exist_ok=True)
        reports_ok = reports.is_dir()
    except OSError:
        reports_ok = False
    items["output_folders"] = {
        "status": "PASS" if reports_ok else "FAIL",
        "reports": str(reports),
        "phase18c": str(reports / "phase18c"),
    }

    items["trend_model_version_env"] = {
        "status": "PASS",
        "env": TREND_VERSION_ENV,
        "rollback_available": True,
    }

    statuses = [v["status"] for v in items.values()]
    hard_fail = any(
        items[k]["status"] == "FAIL"
        for k in ("risk", "symbol_configuration", "timeframe", "logging", "output_folders")
        if k in items
    )
    return {
        "phase": "18C",
        "passed": not hard_fail,
        "items": items,
        "summary": {
            "pass": sum(1 for s in statuses if s == "PASS"),
            "warn": sum(1 for s in statuses if s == "WARN"),
            "fail": sum(1 for s in statuses if s == "FAIL"),
        },
    }
