"""Phase 18C — pre-live verification orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase18c.bundles import validate_bundles
from tradingbot.ml.phase18c.checklist import build_go_live_checklist
from tradingbot.ml.phase18c.config import reports_dir
from tradingbot.ml.phase18c.configuration import validate_configuration
from tradingbot.ml.phase18c.engines import validate_engines
from tradingbot.ml.phase18c.environment import validate_environment
from tradingbot.ml.phase18c.mt5_check import validate_mt5
from tradingbot.ml.phase18c.shutdown import validate_shutdown
from tradingbot.ml.phase18c.startup import validate_startup
from tradingbot.ml.phase18c.verdict import build_checks, build_final_report, determine_verdict


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase18c_prelive(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    base_dir: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    root = project_root or Path(__file__).resolve().parents[3]

    print("phase18c: environment validation ...", flush=True)
    environment = validate_environment(project_root=root)
    _write_json(out / "environment_validation.json", environment)

    print("phase18c: MT5 pre-check (no orders) ...", flush=True)
    mt5 = validate_mt5(symbol=symbol)
    _write_json(out / "mt5_validation.json", mt5)

    print("phase18c: bundle validation ...", flush=True)
    bundles = validate_bundles(base_dir=base_dir)
    _write_json(out / "bundle_validation.json", bundles)

    print("phase18c: engine validation ...", flush=True)
    engines = validate_engines(base_dir=base_dir, symbol=symbol)
    _write_json(out / "engine_validation.json", engines)

    print("phase18c: configuration validation ...", flush=True)
    configuration = validate_configuration(
        project_root=root, symbol=symbol, timeframe=timeframe, base_dir=base_dir,
    )
    _write_json(out / "configuration_validation.json", configuration)

    print("phase18c: startup simulation ...", flush=True)
    startup = validate_startup(project_root=root, base_dir=base_dir, symbol=symbol)
    _write_json(out / "startup_validation.json", startup)

    print("phase18c: shutdown simulation ...", flush=True)
    shutdown = validate_shutdown(base_dir=base_dir, symbol=symbol)
    _write_json(out / "shutdown_validation.json", shutdown)

    checklist = build_go_live_checklist(
        environment=environment,
        mt5=mt5,
        bundles=bundles,
        engines=engines,
        configuration=configuration,
        startup=startup,
        shutdown=shutdown,
    )
    _write_json(out / "go_live_checklist.json", checklist)

    checks = build_checks(
        environment=environment,
        mt5=mt5,
        bundles=bundles,
        engines=engines,
        configuration=configuration,
        startup=startup,
        shutdown=shutdown,
        checklist=checklist,
    )
    verdict = determine_verdict(checks)
    final = build_final_report(
        verdict=verdict,
        checks=checks,
        checklist=checklist,
        environment=environment,
        mt5=mt5,
        bundles=bundles,
        engines=engines,
        configuration=configuration,
        startup=startup,
        shutdown=shutdown,
    )
    _write_json(out / "phase18c_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "checks": checks,
        "checklist": checklist,
    }
