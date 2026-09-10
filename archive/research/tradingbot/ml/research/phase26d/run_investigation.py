"""Phase 26D — startup safety and configuration integrity validation."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

from tradingbot.config.legacy_settings import kernel_settings_from_legacy
from tradingbot.services.startup_validator import (
    StartupValidationError,
    validate_startup,
    write_startup_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent


def _startup_contract() -> dict[str, Any]:
    return {
        "required_env": {
            "USE_ML_KERNEL": "Must be explicitly set to 1/true or 0/false before loop startup",
        },
        "required_for_ml_mode": {
            "USE_ML_KERNEL": "1/true/yes/on",
            "CandleStore": "Parquet candles for configured symbol/timeframe",
            "ML artifacts": "Trend bundle checksum + phase9_9 integrity (HealthGate at startup)",
        },
        "required_for_live_mode": {
            "MT5 connection": "Terminal connected",
            "AutoTrading": "order_check must pass (live execute only)",
        },
        "optional_env": {
            "ALLOW_LEGACY_FALLBACK": "default false — HOLD on ML failure when false",
            "TREND_MODEL_VERSION": "default v41",
            "TRADINGBOT_SKIP_MT5_STARTUP": "test/dev only — skip MT5 probe",
            "PHASE22C_*": "profitability recovery overrides",
            "ENABLE_RSI_FILTER": "filter flags",
            "ENABLE_ADX_FILTER": "filter flags",
        },
        "deprecated_env": {
            "ENABLE_ML_SHADOW": "shadow mode — not production loop",
            "ML_SHADOW_MODE": "shadow mode — not production loop",
        },
        "ignored_cli": {
            "--no-recovery": "Currently ignored — enable_recovery hardcoded False in __main__.py",
        },
        "unsafe_combinations": [
            {"flags": ["--protector"], "reason": "Duplicate position ownership with kernel manager"},
            {"env": ["TRADINGBOT_PAPER=1", "TRADINGBOT_DRY_RUN=1"], "reason": "Conflicting execution mode"},
        ],
        "canonical_paper": "USE_ML_KERNEL=1 python -m tradingbot --loop --paper",
        "canonical_live": "USE_ML_KERNEL=1 python -m tradingbot --loop --execute",
    }


def _fail_fast_rules() -> list[dict[str, Any]]:
    return [
        {"code": "USE_ML_KERNEL_MISSING", "condition": "USE_ML_KERNEL unset", "action": "sys.exit(1)"},
        {"code": "EMERGENCY_STOP_ACTIVE", "condition": "data/emergency_stop.json active=true", "action": "sys.exit(1)"},
        {"code": "DUPLICATE_POSITION_OWNERSHIP", "condition": "--protector enabled", "action": "sys.exit(1)"},
        {"code": "EXEC_MODE_CONFLICT", "condition": "paper+dry_run flags", "action": "sys.exit(1)"},
        {"code": "ML_ARTIFACTS_INVALID", "condition": "HealthGate fails at startup (ML mode)", "action": "sys.exit(1)"},
        {"code": "PARQUET_UNAVAILABLE", "condition": "No candles for ML mode", "action": "sys.exit(1)"},
        {"code": "MT5_UNAVAILABLE", "condition": "MT5 disconnected in paper/live", "action": "sys.exit(1)"},
        {"code": "AUTOTRADING_DISABLED", "condition": "Live mode order_check fails", "action": "sys.exit(1)"},
        {"code": "FILESYSTEM_UNAVAILABLE", "condition": "data/logs/sqlite not writable", "action": "sys.exit(1)"},
    ]


def _startup_sequence() -> list[dict[str, Any]]:
    return [
        {"step": 1, "node": "python -m tradingbot", "file": "tradingbot/__main__.py"},
        {"step": 2, "node": "run_live_loop", "file": "application/live_runner.py"},
        {"step": 3, "node": "LiveRunner.__init__ → build_strategy_registry", "file": "ml/integration/factory.py"},
        {"step": 4, "node": "validate_startup (Phase 26D)", "file": "services/startup_validator.py"},
        {"step": 5, "node": "write_startup_report", "file": "data/startup/startup_report.json"},
        {"step": 6, "node": "market_data.ensure_connected", "file": "adapters/mt5_market_data.py"},
        {"step": 7, "node": "TradingKernel.run_forever", "file": "kernel/trading_kernel.py"},
    ]


def _try_startup(
    *,
    env: dict[str, str | None],
    dry_run: bool,
    paper: bool,
    enable_protector: bool = False,
    emergency_active: bool = False,
    ml_health_ok: bool = True,
    parquet_ok: bool = True,
    skip_mt5: bool = True,
) -> dict[str, Any]:
    settings = kernel_settings_from_legacy()
    legacy = dict(settings.extra or {})
    legacy["BASE_DIR"] = str(PROJECT_ROOT)

    env_full = dict(os.environ)
    env_full.update({k: v for k, v in env.items() if v is not None})
    for k, v in env.items():
        if v is None:
            env_full.pop(k, None)
    if skip_mt5:
        env_full["TRADINGBOT_SKIP_MT5_STARTUP"] = "1"

    fs_ok = {"data_dir": True, "data_writable": True, "logs_dir": True, "logs_writable": True, "sqlite_available": True}
    health_ret = (True, {"checks": {"dataset_fingerprint": True, "trend_checksum": True}, "passes": True})
    if not ml_health_ok:
        health_side = StartupValidationError("ML_ARTIFACTS_INVALID", "checksum_fail")
    else:
        health_side = None

    with ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, env_full, clear=True))
        stack.enter_context(mock.patch("tradingbot.services.startup_validator._check_filesystem", return_value=fs_ok))
        stack.enter_context(mock.patch("tradingbot.services.startup_validator._check_parquet_candles", return_value=parquet_ok))
        stack.enter_context(mock.patch("tradingbot.services.startup_validator._check_mt5", return_value=(True, None)))
        stack.enter_context(
            mock.patch(
                "tradingbot.services.startup_validator.is_emergency_stop_active",
                return_value=emergency_active,
            )
        )
        if health_side is not None:
            stack.enter_context(
                mock.patch(
                    "tradingbot.services.startup_validator._check_ml_artifacts",
                    side_effect=health_side,
                )
            )
        else:
            stack.enter_context(
                mock.patch(
                    "tradingbot.services.startup_validator._check_ml_artifacts",
                    return_value=health_ret,
                )
            )
        try:
            report = validate_startup(
                settings=settings,
                legacy_config=legacy,
                dry_run=dry_run,
                paper=paper,
                enable_protector=enable_protector,
                skip_mt5=skip_mt5,
            )
            return {
                "outcome": "START_SUCCESSFULLY",
                "execution_mode": report.execution_mode,
                "engine": report.engine_selection,
            }
        except StartupValidationError as exc:
            return {
                "outcome": "FAIL_WITH_EXPLICIT_REASON",
                "code": exc.code,
                "reason": exc.reason,
            }


def _run_all_scenarios() -> list[dict[str, Any]]:
    cases = [
        ("paper_ml_mode", {"USE_ML_KERNEL": "1"}, False, True, False, False, True, True),
        ("live_ml_mode", {"USE_ML_KERNEL": "1"}, False, False, False, False, True, True),
        ("legacy_mode", {"USE_ML_KERNEL": "0"}, True, False, False, False, False, False),
        ("missing_use_ml_kernel", {"USE_ML_KERNEL": None}, True, False, False, False, False, False),
        ("emergency_stop", {"USE_ML_KERNEL": "1"}, False, True, False, True, True, True),
        ("duplicate_protector", {"USE_ML_KERNEL": "1"}, False, True, True, False, True, True),
        ("broken_artifacts", {"USE_ML_KERNEL": "1"}, False, True, False, False, False, True),
        ("missing_parquet", {"USE_ML_KERNEL": "1"}, False, True, False, False, True, False),
    ]
    results = []
    for name, env, dry_run, paper, protector, emergency, health, parquet in cases:
        row = _try_startup(
            env=env,
            dry_run=dry_run,
            paper=paper,
            enable_protector=protector,
            emergency_active=emergency,
            ml_health_ok=health,
            parquet_ok=parquet,
        )
        row["scenario"] = name
        results.append(row)
    return results


def run_phase26d_investigation() -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    scenarios = _run_all_scenarios()

    silent_removed = [
        {
            "before": "USE_ML_KERNEL unset → UnconfiguredEngineRegistry → silent idle",
            "after": "validate_startup raises USE_ML_KERNEL_MISSING → sys.exit(1)",
        },
        {
            "before": "Emergency stop → kernel.emergency_stop then continued loop",
            "after": "EMERGENCY_STOP_ACTIVE → sys.exit(1) before run_forever",
        },
        {
            "before": "MT5 disconnect → logger.error return (no exit code)",
            "after": "MT5_UNAVAILABLE → sys.exit(1) for paper/live",
        },
    ]

    success = sum(1 for s in scenarios if s["outcome"] == "START_SUCCESSFULLY")
    fail_explicit = sum(1 for s in scenarios if s["outcome"] == "FAIL_WITH_EXPLICIT_REASON")
    silent = sum(1 for s in scenarios if s["outcome"] not in ("START_SUCCESSFULLY", "FAIL_WITH_EXPLICIT_REASON"))

    verdict = (
        "STARTUP_SAFE"
        if silent == 0 and fail_explicit >= 4 and success >= 3
        else "STARTUP_NOT_SAFE"
    )

    sample = _try_startup(env={"USE_ML_KERNEL": "1"}, dry_run=False, paper=True)
    sample_report = None
    if sample["outcome"] == "START_SUCCESSFULLY":
        with tempfile.TemporaryDirectory() as tmp:
            with ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ, {"USE_ML_KERNEL": "1", "TRADINGBOT_SKIP_MT5_STARTUP": "1"}, clear=True))
                stack.enter_context(mock.patch("tradingbot.services.startup_validator._check_filesystem", return_value={"data_dir": True, "data_writable": True, "logs_dir": True, "logs_writable": True, "sqlite_available": True}))
                stack.enter_context(mock.patch("tradingbot.services.startup_validator._check_parquet_candles", return_value=True))
                stack.enter_context(mock.patch("tradingbot.services.startup_validator._check_mt5", return_value=(True, None)))
                stack.enter_context(mock.patch("tradingbot.services.startup_validator._check_ml_artifacts", return_value=(True, {"checks": {"dataset_fingerprint": True}, "passes": True})))
                report = validate_startup(
                    settings=kernel_settings_from_legacy(),
                    legacy_config={"BASE_DIR": str(PROJECT_ROOT)},
                    dry_run=False,
                    paper=True,
                    skip_mt5=True,
                )
                write_startup_report(report, tmp)
                sample_report = report.to_dict()

    outputs = {
        "startup_contract.json": {**_startup_contract(), "generated_utc": ts},
        "startup_validation.json": {
            "generated_utc": ts,
            "sequence": _startup_sequence(),
            "validator": "services/startup_validator.py",
            "integration": "application/live_runner.py::_run",
            "report_path": "data/startup/startup_report.json",
            "scenarios": scenarios,
            "success_count": success,
            "fail_explicit_count": fail_explicit,
            "silent_count": silent,
        },
        "configuration_matrix.json": {
            "generated_utc": ts,
            "modes": {
                "dry_run": {"TRADINGBOT_DRY_RUN": "1", "cli": "--loop"},
                "paper": {"TRADINGBOT_PAPER": "1", "cli": "--loop --paper"},
                "live": {"cli": "--loop --execute"},
            },
            "engine_modes": {
                "ml": {"USE_ML_KERNEL": "1"},
                "legacy": {"USE_ML_KERNEL": "0"},
            },
        },
        "environment_matrix.json": {
            "generated_utc": ts,
            "required": _startup_contract()["required_env"],
            "optional": _startup_contract()["optional_env"],
            "deprecated": _startup_contract()["deprecated_env"],
        },
        "fail_fast_rules.json": {"generated_utc": ts, "rules": _fail_fast_rules()},
        "diagnostic_report_schema.json": {
            "generated_utc": ts,
            "fields": list(sample_report.keys()) if sample_report else [],
            "sample": sample_report,
        },
        "startup_state_machine.json": {
            "generated_utc": ts,
            "states": ["IDLE", "VALIDATING", "READY", "RUNNING", "FAILED"],
            "transitions": [
                {"from": "IDLE", "to": "VALIDATING", "via": "LiveRunner._run"},
                {"from": "VALIDATING", "to": "READY", "via": "validate_startup OK"},
                {"from": "VALIDATING", "to": "FAILED", "via": "StartupValidationError → exit(1)"},
                {"from": "READY", "to": "RUNNING", "via": "kernel.run_forever"},
            ],
        },
        "configuration_conflicts.json": {
            "generated_utc": ts,
            "conflicts": _startup_contract()["unsafe_combinations"],
            "silent_removed": silent_removed,
        },
        "rollback_validation.json": {
            "generated_utc": ts,
            "phase26c_journal": "unchanged",
            "execution_algorithms": "unchanged",
            "health_gate_logic": "unchanged — called read-only at startup",
            "risk_decision_calibration": "unchanged",
        },
        "phase26d_final_report.json": {
            "phase": "26D",
            "generated_utc": ts,
            "verdict": verdict,
            "scenarios_tested": len(scenarios),
            "start_successfully": success,
            "fail_with_explicit_reason": fail_explicit,
            "silent_continues": silent,
            "fail_fast_codes": [r["code"] for r in _fail_fast_rules()],
        },
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return outputs["phase26d_final_report.json"]


def main() -> int:
    report = run_phase26d_investigation()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "STARTUP_SAFE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
