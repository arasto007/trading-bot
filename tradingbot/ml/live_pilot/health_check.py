"""Phase 12 — pre-live health check."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import live_pilot_run_dir, phase12_live_pilot_report_path
from tradingbot.ml.live_pilot.config import PilotConfig, is_pilot_live_enabled, resolve_mode
from tradingbot.ml.live_pilot.kill_switch import PilotKillSwitch
from tradingbot.ml.live_pilot.position_limiter import PositionLimiter
from tradingbot.ml.live_pilot.safety_manager import SafetyManager
from tradingbot.ml.paper.config import validate_frozen_model

logger = logging.getLogger(__name__)

LIVE_PILOT_PKG = Path(__file__).resolve().parent
ORDER_SEND_ALLOWED_FILE = "execution_guard.py"


def scan_phase12_ast(pkg_root: Path | None = None) -> list[str]:
    """AST scan — Mt5ExecutionAdapter import only permitted in execution_guard.py."""
    root = pkg_root or LIVE_PILOT_PKG
    violations: list[str] = []
    allowed = {ORDER_SEND_ALLOWED_FILE}
    forbidden_modules = ("mt5_execution", "Mt5ExecutionAdapter")
    for path in root.rglob("*.py"):
        if path.name in allowed or path.name == "__init__.py":
            continue
        rel = path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Call):
                func = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if func == "order_send":
                    violations.append(f"{rel}: call order_send")
                continue
            else:
                continue
            for module in mods:
                for token in forbidden_modules:
                    if token in module:
                        violations.append(f"{rel}: import {module}")
    return violations


def run_health_check(
    *,
    config: PilotConfig | None = None,
    base_dir: str | Path | None = None,
    run_preflight: bool = True,
) -> dict[str, Any]:
    cfg = config or PilotConfig()
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # AST safety
    ast_violations = scan_phase12_ast()
    checks["ast_clean"] = len(ast_violations) == 0
    if ast_violations:
        errors.extend(ast_violations)

    # Model validation
    try:
        model_report = validate_frozen_model(base_dir=base_dir)
        checks["model_checksum"] = model_report.get("status") == "PASS"
        checks["feature_order"] = bool(model_report.get("feature_order"))
    except Exception as exc:
        checks["model_checksum"] = False
        errors.append(f"model_validation: {exc}")
        model_report = {"status": "FAIL", "error": str(exc)}

    # Risk configuration
    checks["risk_config"] = 0 < cfg.risk_pct <= 0.01
    checks["max_positions"] = cfg.max_open_positions == 1
    checks["max_daily_loss"] = cfg.max_daily_loss_pct == 0.02

    # Safety layer components
    ks = PilotKillSwitch()
    pl = PositionLimiter(max_open_positions=cfg.max_open_positions)
    sm = SafetyManager(cfg, kill_switch=ks, position_limiter=pl, model_checksum_valid=checks.get("model_checksum", False))
    checks["safety_layer"] = sm is not None and isinstance(sm.kill_switch, PilotKillSwitch)
    checks["kill_switch"] = not ks.active

    # Journal writable
    run_dir = live_pilot_run_dir(cfg.run_id, base_dir)
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        probe = run_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks["journal_writable"] = True
    except OSError as exc:
        checks["journal_writable"] = False
        errors.append(f"journal: {exc}")

    # Execution status
    mode = resolve_mode(cfg.mode)
    pilot_enabled = is_pilot_live_enabled()
    checks["execution_disabled_by_default"] = mode != "PILOT" or not pilot_enabled
    checks["pilot_requires_dual_approval"] = (mode != "PILOT") or pilot_enabled

    # MT5 preflight
    preflight: dict[str, Any] = {}
    if run_preflight:
        try:
            from tradingbot.adapters.legacy_loader import load_legacy_config
            from tradingbot.ml.integration.live_preflight import run_live_preflight

            legacy = load_legacy_config()
            legacy["RISK_PER_TRADE"] = cfg.risk_pct
            preflight = run_live_preflight(cfg.symbol, cfg.timeframe, config=legacy, base_dir=base_dir)
            checks["mt5_connection"] = bool(preflight.get("connection_ok"))
            checks["symbol_available"] = bool(preflight.get("symbol_available"))
        except Exception as exc:
            checks["mt5_connection"] = False
            errors.append(f"preflight: {exc}")
    else:
        checks["mt5_connection"] = True
        checks["symbol_available"] = True
        preflight = {"skipped": True}

    passed = all(checks.values()) and not errors
    report = {
        "phase": "12",
        "health_check": "PASS" if passed else "FAIL",
        "checks": checks,
        "errors": errors,
        "mode": mode,
        "pilot_live_enabled": pilot_enabled,
        "execution_guard_module": ORDER_SEND_ALLOWED_FILE,
        "model_validation": model_report,
        "preflight": preflight,
        "config": cfg.to_dict(),
    }

    out = phase12_live_pilot_report_path(base_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"health_check": report}, indent=2), encoding="utf-8")
    return report
