"""Phase 10 — shadow run persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    ml_shadow_config_path,
    ml_shadow_kernel_decisions_path,
    ml_shadow_metrics_path,
    ml_shadow_report_path,
    ml_shadow_risk_decisions_path,
    ml_shadow_run_dir,
    ml_shadow_signals_path,
    ml_shadow_virtual_trades_path,
)


def save_shadow_run(
    run_id: str,
    *,
    signals: list[dict[str, Any]],
    kernel_decisions: list[dict[str, Any]],
    risk_decisions: list[dict[str, Any]],
    virtual_trades: list[dict[str, Any]],
    metrics: dict[str, Any],
    config: dict[str, Any],
    extra: dict[str, Any] | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    run_dir = ml_shadow_run_dir(run_id, base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    ml_shadow_signals_path(run_id, base_dir).write_text(json.dumps(signals, indent=2), encoding="utf-8")
    ml_shadow_kernel_decisions_path(run_id, base_dir).write_text(
        json.dumps(kernel_decisions, indent=2), encoding="utf-8"
    )
    ml_shadow_risk_decisions_path(run_id, base_dir).write_text(
        json.dumps(risk_decisions, indent=2), encoding="utf-8"
    )
    ml_shadow_virtual_trades_path(run_id, base_dir).write_text(
        json.dumps(virtual_trades, indent=2), encoding="utf-8"
    )
    ml_shadow_metrics_path(run_id, base_dir).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    ml_shadow_config_path(run_id, base_dir).write_text(json.dumps(config, indent=2), encoding="utf-8")

    report = {
        "run_id": run_id,
        "phase": "10",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "config": config,
        "num_signals": len(signals),
        "num_virtual_trades": len(virtual_trades),
        "order_send": False,
        "shadow_only": True,
    }
    if extra:
        report.update(extra)

    ml_shadow_report_path(run_id, base_dir).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "run_dir": run_dir,
        "signals": ml_shadow_signals_path(run_id, base_dir),
        "kernel_decisions": ml_shadow_kernel_decisions_path(run_id, base_dir),
        "risk_decisions": ml_shadow_risk_decisions_path(run_id, base_dir),
        "virtual_trades": ml_shadow_virtual_trades_path(run_id, base_dir),
        "metrics": ml_shadow_metrics_path(run_id, base_dir),
        "config": ml_shadow_config_path(run_id, base_dir),
        "report": ml_shadow_report_path(run_id, base_dir),
    }


def load_shadow_report(run_id: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    path = ml_shadow_report_path(run_id, base_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Shadow run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))
