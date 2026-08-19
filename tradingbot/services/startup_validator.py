"""Fail-fast startup validation before TradingKernel.run_forever()."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.adapters.legacy_loader import project_root
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.settings import KernelSettings
from tradingbot.ml.data.paths import normalize_ml_base_dir
from tradingbot.ml.integration.config import (
    is_legacy_fallback_allowed,
    is_ml_kernel_enabled,
    is_ml_kernel_env_set,
    ml_kernel_config_from_env,
)
from tradingbot.ml.integration.startup_diagnostics import resolve_engine_selection
from tradingbot.services.emergency_stop_state import is_emergency_stop_active, read_emergency_stop
from tradingbot.services.execution_mode import is_dry_run, is_live_execute, is_paper, mode_label

logger = logging.getLogger(__name__)


class StartupValidationError(Exception):
    """Startup refused — trading loop must not begin."""

    def __init__(self, code: str, reason: str, *, checks: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.checks = checks or {}


@dataclass
class StartupDiagnosticReport:
    startup_timestamp: str
    execution_mode: str
    engine_selection: str
    ml_kernel_enabled: bool
    legacy_fallback_allowed: bool
    emergency_stop_active: bool
    mt5_connected: bool
    autotrading_ready: bool | None
    health_gate_passes: bool | None
    model_versions: dict[str, str]
    artifact_fingerprints: dict[str, Any]
    dataset_fingerprint_ok: bool | None
    risk_mode: str
    recovery_mode: bool
    position_manager: str
    protector_enabled: bool
    health_status: str
    configuration_summary: dict[str, Any]
    repository_version: str
    account_balance: float | None = None
    account_equity: float | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _repo_version() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _resolve_execution_mode(*, dry_run: bool, paper: bool) -> str:
    if paper:
        return "paper"
    if dry_run:
        return "dry_run"
    return "live"


def _check_execution_mode_flags(*, dry_run: bool, paper: bool) -> None:
    if paper and dry_run:
        raise StartupValidationError(
            "EXEC_MODE_CONFLICT",
            "Paper and dry-run flags conflict — only one execution mode allowed",
        )
    env_paper = os.environ.get("TRADINGBOT_PAPER", "").lower() in ("1", "true", "yes")
    env_dry = os.environ.get("TRADINGBOT_DRY_RUN", "").lower() in ("1", "true", "yes")
    if env_paper and env_dry:
        raise StartupValidationError(
            "EXEC_ENV_CONFLICT",
            "TRADINGBOT_PAPER and TRADINGBOT_DRY_RUN cannot both be set",
        )


def _check_use_ml_kernel() -> dict[str, Any]:
    selection = resolve_engine_selection()
    if not selection.ml_kernel_env_present:
        raise StartupValidationError(
            "USE_ML_KERNEL_MISSING",
            selection.reason,
            checks=selection.to_dict(),
        )
    return selection.to_dict()


def _check_emergency_stop() -> dict[str, Any] | None:
    if is_emergency_stop_active():
        snap = read_emergency_stop() or {}
        raise StartupValidationError(
            "EMERGENCY_STOP_ACTIVE",
            f"Emergency stop active — explicit reset required | reason={snap.get('reason')}",
            checks={"emergency_stop": True, "snapshot": snap},
        )
    return None


def _check_duplicate_ownership(*, enable_protector: bool) -> None:
    if enable_protector:
        raise StartupValidationError(
            "DUPLICATE_POSITION_OWNERSHIP",
            "PositionProtector (--protector) conflicts with kernel Mt5PositionManager — disable --protector",
            checks={"protector_enabled": True, "kernel_position_manager": True},
        )


def _check_filesystem(base_dir: str | Path) -> dict[str, bool]:
    root = Path(base_dir)
    checks: dict[str, bool] = {}
    for name in ("data", "logs"):
        path = root / name if name != "data" else root / "data"
        path.mkdir(parents=True, exist_ok=True)
        checks[f"{name}_dir"] = path.is_dir()
        try:
            probe = path / ".startup_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            checks[f"{name}_writable"] = True
        except OSError:
            checks[f"{name}_writable"] = False
    db_path = root / "data" / "trade_journal.db"
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("SELECT 1")
        checks["sqlite_available"] = True
    except Exception:
        checks["sqlite_available"] = False
    if not all(checks.values()):
        failed = [k for k, v in checks.items() if not v]
        raise StartupValidationError(
            "FILESYSTEM_UNAVAILABLE",
            f"Required filesystem checks failed: {', '.join(failed)}",
            checks=checks,
        )
    return checks


def _check_parquet_candles(base_dir: str, symbol: str, timeframe: str) -> bool:
    try:
        from tradingbot.ml.data.stores.candle_store import CandleStore

        candles = CandleStore(base_dir).load(symbol, timeframe)
        return candles is not None and not candles.empty
    except Exception:
        return False


def _check_ml_artifacts(*, base_dir: str, symbol: str) -> tuple[bool, dict[str, Any]]:
    from tradingbot.ml.integration.health_gate import run_pre_decision_health
    from tradingbot.ml.integration.pipeline_cache import PipelineCache

    PipelineCache.configure(base_dir=base_dir, symbol=symbol)
    registry = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
    health = run_pre_decision_health(registry=registry, base_dir=base_dir, unified_row=None)
    if not health.passes:
        raise StartupValidationError(
            "ML_ARTIFACTS_INVALID",
            "; ".join(health.errors) or "health_gate_failed",
            checks=health.to_dict(),
        )
    return True, health.to_dict()


def _check_mt5(
    *,
    symbol: str,
    config: dict[str, Any],
    execution_mode: str,
    skip_mt5: bool,
) -> tuple[bool, bool | None]:
    if skip_mt5:
        return True, None

    from tradingbot.adapters.mt5_health import check_autotrading_ready, check_mt5_health
    from tradingbot.adapters.mt5_utils import attach_mt5_session
    from tradingbot.adapters.symbols import resolve_broker_symbol

    broker = resolve_broker_symbol(symbol, config)
    if not attach_mt5_session(config, symbols=[symbol], strict_account=False):
        reason = "terminal not connected"
        if execution_mode == "dry_run":
            logger.warning("MT5 attach failed in dry-run - market data may be unavailable")
            return False, None
        raise StartupValidationError(
            "MT5_UNAVAILABLE",
            reason,
            checks={"connected": False, "reason": reason},
        )
    health = check_mt5_health(broker)
    if not health.connected:
        if execution_mode == "dry_run":
            logger.warning("MT5 not connected in dry-run — market data may be unavailable")
            return False, None
        raise StartupValidationError(
            "MT5_UNAVAILABLE",
            health.reason or "MT5 terminal not connected",
            checks={"connected": False, "reason": health.reason},
        )

    autotrading: bool | None = None
    if execution_mode == "live":
        ok, reason = check_autotrading_ready(symbol, config=config)
        autotrading = ok
        if not ok:
            raise StartupValidationError(
                "AUTOTRADING_DISABLED",
                reason,
                checks={"autotrading_ready": False},
            )
        from tradingbot.services.demo_account_guard import verify_demo_account_or_abort

        demo_ok, demo_msg = verify_demo_account_or_abort(config=config)
        if not demo_ok:
            raise StartupValidationError(
                "REAL_ACCOUNT_BLOCKED",
                demo_msg,
                checks={"demo_account": False, "reason": demo_msg},
            )
    return True, autotrading


def validate_startup(
    *,
    settings: KernelSettings,
    legacy_config: dict[str, Any],
    dry_run: bool = True,
    paper: bool = False,
    enable_protector: bool = False,
    enable_recovery: bool = False,
    skip_mt5: bool = False,
) -> StartupDiagnosticReport:
    """
    Validate startup configuration. Raises StartupValidationError on any critical failure.
    """
    raw_base_dir = legacy_config.get("BASE_DIR", str(settings.base_dir))
    project_dir = str(raw_base_dir) if raw_base_dir else str(project_root())
    ml_base_dir = normalize_ml_base_dir(raw_base_dir)
    symbol = settings.symbols[0] if settings.symbols else PRIMARY_SYMBOL
    timeframe = settings.timeframes[0] if settings.timeframes else "M5"
    execution_mode = _resolve_execution_mode(dry_run=dry_run, paper=paper)
    checks: dict[str, bool] = {}

    _check_execution_mode_flags(dry_run=dry_run, paper=paper)
    checks["execution_mode_resolved"] = True

    engine_info = _check_use_ml_kernel()
    checks["use_ml_kernel_set"] = True

    _check_emergency_stop()
    checks["emergency_stop_clear"] = True

    _check_duplicate_ownership(enable_protector=enable_protector)
    checks["single_position_owner"] = True

    fs_checks = _check_filesystem(project_dir)
    checks.update(fs_checks)

    ml_enabled = is_ml_kernel_enabled()
    health_passes: bool | None = None
    artifact_info: dict[str, Any] = {}
    dataset_fp_ok: bool | None = None

    if ml_enabled:
        parquet_ok = _check_parquet_candles(ml_base_dir, symbol, timeframe)
        checks["parquet_candles"] = parquet_ok
        if not parquet_ok:
            raise StartupValidationError(
                "PARQUET_UNAVAILABLE",
                f"CandleStore empty for {symbol} {timeframe} — required for ML kernel",
                checks={"parquet_candles": False},
            )
        health_passes, artifact_info = _check_ml_artifacts(base_dir=ml_base_dir, symbol=symbol)
        checks["health_gate"] = health_passes
        dataset_fp_ok = bool(artifact_info.get("checks", {}).get("dataset_fingerprint"))

    mt5_connected, autotrading = _check_mt5(
        symbol=symbol,
        config=legacy_config,
        execution_mode=execution_mode,
        skip_mt5=skip_mt5,
    )
    checks["mt5_connected"] = mt5_connected or skip_mt5

    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version

    model_versions = {
        "trend_bundle": resolve_bundle_version(),
        "trend_engine": resolve_active_trend_engine_id(),
        "trend_model_env": os.environ.get("TREND_MODEL_VERSION", "v41"),
    }

    env_summary = ml_kernel_config_from_env()
    env_summary["execution_mode"] = execution_mode
    env_summary["TRADINGBOT_PAPER"] = is_paper()
    env_summary["TRADINGBOT_DRY_RUN"] = is_dry_run()
    env_summary["TRADINGBOT_LIVE"] = is_live_execute()

    from tradingbot.config.prop_presets import PRESETS, active_preset_name

    preset_name = active_preset_name()
    env_summary["TRADINGBOT_PROP_PRESET"] = preset_name
    env_summary["PROP_FIRM_PRESET"] = legacy_config.get("PROP_FIRM_PRESET", "none")
    report_warnings: list[str] = []
    if not (os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip()):
        report_warnings.append("Telegram alerts optional — TELEGRAM_BOT_TOKEN/CHAT_ID not set")
    if preset_name not in ("none", "") and preset_name not in PRESETS:
        report_warnings.append(f"Unknown TRADINGBOT_PROP_PRESET={preset_name!r} — using base config")
    elif preset_name not in ("none", ""):
        report_warnings.append(
            f"Prop preset active: {preset_name} ({legacy_config.get('PROP_FIRM_NAME', preset_name)})"
        )

    health_status = "READY"
    from tradingbot.config.live import get_live_config

    vol_on = bool(get_live_config().get("VOL_REGIME_ENABLED", False))
    if ml_enabled and health_passes:
        health_status = "ML_HEALTH_OK"
    elif vol_on and not ml_enabled:
        health_status = "VOL_REGIME_MODE"
    elif not ml_enabled:
        health_status = "LEGACY_MODE"

    account_balance: float | None = None
    account_equity: float | None = None
    if mt5_connected and not skip_mt5:
        try:
            import MetaTrader5 as mt5

            acc = mt5.account_info()
            if acc is not None:
                account_balance = float(acc.balance)
                account_equity = float(acc.equity)
        except Exception:
            pass

    report = StartupDiagnosticReport(
        startup_timestamp=datetime.now(timezone.utc).isoformat(),
        execution_mode=execution_mode,
        engine_selection=str(engine_info.get("selected_engine", "")),
        ml_kernel_enabled=ml_enabled,
        legacy_fallback_allowed=is_legacy_fallback_allowed(),
        emergency_stop_active=False,
        mt5_connected=mt5_connected,
        autotrading_ready=autotrading,
        health_gate_passes=health_passes,
        model_versions=model_versions,
        artifact_fingerprints=artifact_info.get("checks", {}),
        dataset_fingerprint_ok=dataset_fp_ok,
        risk_mode="RiskGate+AdaptiveRisk" if ml_enabled else "RiskGate+Legacy",
        recovery_mode=enable_recovery,
        position_manager="Mt5PositionManager",
        protector_enabled=enable_protector,
        health_status=health_status,
        configuration_summary=env_summary,
        repository_version=_repo_version(),
        account_balance=account_balance,
        account_equity=account_equity,
        checks=checks,
        warnings=report_warnings,
    )
    return report


def write_startup_report(report: StartupDiagnosticReport, base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir or ".")
    out_dir = root / "data" / "startup"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "startup_report.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path


def log_startup_report(report: StartupDiagnosticReport) -> None:
    logger.info(
        "STARTUP OK | mode=%s | engine=%s | ml=%s | fallback=%s | health=%s",
        report.execution_mode,
        report.engine_selection,
        report.ml_kernel_enabled,
        report.legacy_fallback_allowed,
        report.health_status,
    )
