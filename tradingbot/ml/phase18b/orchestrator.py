"""Phase 18B — controlled live gate orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.phase18b.checklist import build_final_checklist
from tradingbot.ml.phase18b.config import reports_dir
from tradingbot.ml.phase18b.failure_injection import run_failure_injection
from tradingbot.ml.phase18b.health import run_health_report
from tradingbot.ml.phase18b.live_safety import run_live_safety
from tradingbot.ml.phase18b.operational import run_operational_readiness
from tradingbot.ml.phase18b.production_audit import run_production_audit
from tradingbot.ml.phase18b.rollback import run_rollback_cycles
from tradingbot.ml.phase18b.stability import run_stability
from tradingbot.ml.phase18b.verdict import (
    build_final_report,
    build_go_live_checks,
    build_go_live_recommendation,
    determine_verdict,
)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase18b_go_live(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    base_dir: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    root = project_root or Path(__file__).resolve().parents[3]

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    print("phase18b: production audit ...", flush=True)
    audit = run_production_audit(project_root=root, base_dir=base_dir, symbol=symbol)
    _write_json(out / "production_audit.json", audit)

    print("phase18b: failure injection ...", flush=True)
    failure = run_failure_injection(base_dir=base_dir, symbol=symbol)
    _write_json(out / "failure_injection.json", failure)

    print("phase18b: long-run stability (365d stride 1+5) ...", flush=True)
    stability = run_stability(
        candles, dataset, base_dir=base_dir, symbol=symbol, days=days,
    )
    _write_json(out / "stability_report.json", stability)

    print("phase18b: rollback cycles ...", flush=True)
    rollback = run_rollback_cycles(base_dir=base_dir, symbol=symbol)
    _write_json(out / "rollback_report.json", rollback)

    print("phase18b: live safety ...", flush=True)
    live_safety = run_live_safety(project_root=root, base_dir=base_dir, symbol=symbol)
    # live safety report is embedded; also write health
    print("phase18b: health report ...", flush=True)
    health = run_health_report(base_dir=base_dir, symbol=symbol)
    _write_json(out / "health_report.json", health)

    print("phase18b: operational readiness ...", flush=True)
    operational = run_operational_readiness(project_root=root, base_dir=base_dir, symbol=symbol)
    _write_json(out / "operational_readiness.json", operational)

    checklist = build_final_checklist(
        audit=audit,
        failure=failure,
        stability=stability,
        rollback=rollback,
        live_safety=live_safety,
        operational=operational,
        health=health,
    )
    _write_json(out / "final_checklist.json", checklist)

    checks = build_go_live_checks(
        audit=audit,
        failure=failure,
        stability=stability,
        rollback=rollback,
        live_safety=live_safety,
        operational=operational,
        checklist=checklist,
    )
    verdict = determine_verdict(checks)
    recommendation = build_go_live_recommendation(
        verdict=verdict, checks=checks, checklist=checklist,
    )
    _write_json(out / "go_live_recommendation.json", recommendation)

    final = build_final_report(
        verdict=verdict,
        checks=checks,
        checklist=checklist,
        recommendation=recommendation,
        audit=audit,
        failure=failure,
        stability=stability,
        rollback=rollback,
        live_safety=live_safety,
        operational=operational,
    )
    _write_json(out / "phase18b_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "checks": checks,
        "checklist": checklist,
    }
