"""Phase 10.1 — kernel shadow run persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    ml_kernel_shadow_config_path,
    ml_kernel_shadow_context_path,
    ml_kernel_shadow_events_path,
    ml_kernel_shadow_execution_blocked_path,
    ml_kernel_shadow_metrics_path,
    ml_kernel_shadow_report_path,
    ml_kernel_shadow_risk_path,
    ml_kernel_shadow_run_dir,
    ml_kernel_shadow_signals_path,
    ml_kernel_shadow_virtual_trades_path,
)


def save_kernel_shadow_run(
    run_id: str,
    *,
    events: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    kernel_context: list[dict[str, Any]],
    risk_results: list[dict[str, Any]],
    execution_blocked: list[dict[str, Any]],
    virtual_trades: list[dict[str, Any]],
    metrics: dict[str, Any],
    config: dict[str, Any],
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    run_dir = ml_kernel_shadow_run_dir(run_id, base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    ml_kernel_shadow_events_path(run_id, base_dir).write_text(json.dumps(events, indent=2), encoding="utf-8")
    ml_kernel_shadow_signals_path(run_id, base_dir).write_text(json.dumps(signals, indent=2), encoding="utf-8")
    ml_kernel_shadow_context_path(run_id, base_dir).write_text(json.dumps(kernel_context, indent=2), encoding="utf-8")
    ml_kernel_shadow_risk_path(run_id, base_dir).write_text(json.dumps(risk_results, indent=2), encoding="utf-8")
    ml_kernel_shadow_execution_blocked_path(run_id, base_dir).write_text(
        json.dumps(execution_blocked, indent=2), encoding="utf-8"
    )
    ml_kernel_shadow_virtual_trades_path(run_id, base_dir).write_text(
        json.dumps(virtual_trades, indent=2), encoding="utf-8"
    )
    ml_kernel_shadow_metrics_path(run_id, base_dir).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    ml_kernel_shadow_config_path(run_id, base_dir).write_text(json.dumps(config, indent=2), encoding="utf-8")

    report = {
        "run_id": run_id,
        "phase": "10.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "config": config,
        "order_send": False,
        "kernel_integrated": True,
    }
    ml_kernel_shadow_report_path(run_id, base_dir).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "run_dir": run_dir,
        "events": ml_kernel_shadow_events_path(run_id, base_dir),
        "signals": ml_kernel_shadow_signals_path(run_id, base_dir),
        "kernel_context": ml_kernel_shadow_context_path(run_id, base_dir),
        "risk_results": ml_kernel_shadow_risk_path(run_id, base_dir),
        "execution_blocked": ml_kernel_shadow_execution_blocked_path(run_id, base_dir),
        "virtual_trades": ml_kernel_shadow_virtual_trades_path(run_id, base_dir),
        "metrics": ml_kernel_shadow_metrics_path(run_id, base_dir),
        "report": ml_kernel_shadow_report_path(run_id, base_dir),
    }


def load_kernel_shadow_report(run_id: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    path = ml_kernel_shadow_report_path(run_id, base_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Kernel shadow run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))
