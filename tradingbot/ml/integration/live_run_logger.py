"""Phase 10.2 — live shadow run persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    ml_live_shadow_config_path,
    ml_live_shadow_context_path,
    ml_live_shadow_equity_path,
    ml_live_shadow_events_path,
    ml_live_shadow_metrics_path,
    ml_live_shadow_report_path,
    ml_live_shadow_risk_path,
    ml_live_shadow_run_dir,
    ml_live_shadow_signals_path,
    ml_live_shadow_virtual_orders_path,
    ml_live_shadow_virtual_trades_path,
)


def save_live_shadow_run(
    run_id: str,
    *,
    events: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    kernel_context: list[dict[str, Any]],
    risk_results: list[dict[str, Any]],
    virtual_orders: list[dict[str, Any]],
    virtual_trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    metrics: dict[str, Any],
    config: dict[str, Any],
    extra: dict[str, Any] | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    run_dir = ml_live_shadow_run_dir(run_id, base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    ml_live_shadow_events_path(run_id, base_dir).write_text(json.dumps(events, indent=2), encoding="utf-8")
    ml_live_shadow_signals_path(run_id, base_dir).write_text(json.dumps(signals, indent=2), encoding="utf-8")
    ml_live_shadow_context_path(run_id, base_dir).write_text(json.dumps(kernel_context, indent=2), encoding="utf-8")
    ml_live_shadow_risk_path(run_id, base_dir).write_text(json.dumps(risk_results, indent=2), encoding="utf-8")
    ml_live_shadow_virtual_orders_path(run_id, base_dir).write_text(
        json.dumps(virtual_orders, indent=2), encoding="utf-8"
    )
    ml_live_shadow_virtual_trades_path(run_id, base_dir).write_text(
        json.dumps(virtual_trades, indent=2), encoding="utf-8"
    )
    ml_live_shadow_equity_path(run_id, base_dir).write_text(json.dumps(equity_curve, indent=2), encoding="utf-8")
    ml_live_shadow_metrics_path(run_id, base_dir).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    ml_live_shadow_config_path(run_id, base_dir).write_text(json.dumps(config, indent=2), encoding="utf-8")

    report = {
        "run_id": run_id,
        "phase": "10.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "config": config,
        "order_send": False,
        "kernel_integrated": True,
        "live_shadow": True,
    }
    if extra:
        report.update(extra)

    ml_live_shadow_report_path(run_id, base_dir).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "run_dir": run_dir,
        "events": ml_live_shadow_events_path(run_id, base_dir),
        "signals": ml_live_shadow_signals_path(run_id, base_dir),
        "kernel_context": ml_live_shadow_context_path(run_id, base_dir),
        "risk_results": ml_live_shadow_risk_path(run_id, base_dir),
        "virtual_orders": ml_live_shadow_virtual_orders_path(run_id, base_dir),
        "virtual_trades": ml_live_shadow_virtual_trades_path(run_id, base_dir),
        "equity_curve": ml_live_shadow_equity_path(run_id, base_dir),
        "metrics": ml_live_shadow_metrics_path(run_id, base_dir),
        "report": ml_live_shadow_report_path(run_id, base_dir),
    }


def load_live_shadow_report(run_id: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    path = ml_live_shadow_report_path(run_id, base_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Live shadow run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))
