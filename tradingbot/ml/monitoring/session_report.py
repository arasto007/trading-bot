"""Phase 10.4 — persist shadow monitor session artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    ml_shadow_monitor_anomalies_path,
    ml_shadow_monitor_config_path,
    ml_shadow_monitor_equity_path,
    ml_shadow_monitor_final_report_path,
    ml_shadow_monitor_hourly_path,
    ml_shadow_monitor_risk_path,
    ml_shadow_monitor_run_dir,
    ml_shadow_monitor_signals_path,
    ml_shadow_monitor_trade_quality_path,
    phase10_4_stability_report_path,
)


def save_monitor_session(
    run_id: str,
    *,
    config: dict[str, Any],
    hourly_metrics: list[dict[str, Any]],
    signals_summary: dict[str, Any],
    risk_summary: dict[str, Any],
    trade_quality: list[dict[str, Any]],
    anomalies: dict[str, Any],
    equity_curve: list[dict[str, Any]],
    final_report: dict[str, Any],
    base_dir: str | Path | None = None,
    write_global_stability: bool = True,
) -> dict[str, Path]:
    root = ml_shadow_monitor_run_dir(run_id, base_dir)
    root.mkdir(parents=True, exist_ok=True)

    ml_shadow_monitor_config_path(run_id, base_dir).write_text(json.dumps(config, indent=2), encoding="utf-8")
    ml_shadow_monitor_hourly_path(run_id, base_dir).write_text(
        json.dumps(hourly_metrics, indent=2), encoding="utf-8"
    )
    ml_shadow_monitor_signals_path(run_id, base_dir).write_text(
        json.dumps(signals_summary, indent=2), encoding="utf-8"
    )
    ml_shadow_monitor_risk_path(run_id, base_dir).write_text(json.dumps(risk_summary, indent=2), encoding="utf-8")
    ml_shadow_monitor_trade_quality_path(run_id, base_dir).write_text(
        json.dumps(trade_quality, indent=2), encoding="utf-8"
    )
    ml_shadow_monitor_anomalies_path(run_id, base_dir).write_text(json.dumps(anomalies, indent=2), encoding="utf-8")
    ml_shadow_monitor_equity_path(run_id, base_dir).write_text(json.dumps(equity_curve, indent=2), encoding="utf-8")
    ml_shadow_monitor_final_report_path(run_id, base_dir).write_text(
        json.dumps(final_report, indent=2), encoding="utf-8"
    )

    if write_global_stability:
        global_report = {
            "phase": "10.4",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            **final_report,
        }
        phase10_4_stability_report_path(base_dir).write_text(
            json.dumps(global_report, indent=2), encoding="utf-8"
        )

    return {
        "run_dir": root,
        "config": ml_shadow_monitor_config_path(run_id, base_dir),
        "hourly_metrics": ml_shadow_monitor_hourly_path(run_id, base_dir),
        "signals_summary": ml_shadow_monitor_signals_path(run_id, base_dir),
        "risk_summary": ml_shadow_monitor_risk_path(run_id, base_dir),
        "trade_quality": ml_shadow_monitor_trade_quality_path(run_id, base_dir),
        "anomalies": ml_shadow_monitor_anomalies_path(run_id, base_dir),
        "equity_curve": ml_shadow_monitor_equity_path(run_id, base_dir),
        "final_report": ml_shadow_monitor_final_report_path(run_id, base_dir),
    }
