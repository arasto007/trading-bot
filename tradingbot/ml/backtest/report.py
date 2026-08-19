"""Backtest report persistence for Phase 8.7."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    backtest_config_path,
    backtest_equity_path,
    backtest_metrics_path,
    backtest_report_path,
    backtest_run_dir,
    backtest_trades_path,
    next_backtest_run_id,
)
from tradingbot.ml.backtest.metrics import BacktestMetrics
from tradingbot.ml.backtest.state import BacktestState


def save_backtest_run(
    run_id: str,
    state: BacktestState,
    metrics: BacktestMetrics,
    config: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Path]:
    run_dir = backtest_run_dir(run_id, base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    equity_path = backtest_equity_path(run_id, base_dir)
    equity_path.write_text(
        json.dumps([p.to_dict() for p in state.equity_curve], indent=2),
        encoding="utf-8",
    )

    trades_path = backtest_trades_path(run_id, base_dir)
    trades_path.write_text(
        json.dumps([t.to_dict() for t in state.closed_trades], indent=2),
        encoding="utf-8",
    )

    metrics_path = backtest_metrics_path(run_id, base_dir)
    metrics_path.write_text(json.dumps(metrics.to_dict(), indent=2), encoding="utf-8")

    config_path = backtest_config_path(run_id, base_dir)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    report = {
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "initial_equity": state.initial_equity,
        "final_equity": state.equity,
        "num_trades": metrics.num_trades,
        "metrics": metrics.to_dict(),
        "config": config,
    }
    if extra:
        report.update(extra)

    report_path = backtest_report_path(run_id, base_dir)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "run_dir": run_dir,
        "equity_curve": equity_path,
        "trades": trades_path,
        "metrics": metrics_path,
        "config": config_path,
        "report": report_path,
    }


def load_backtest_run(run_id: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    rid = str(run_id)
    if not rid.startswith("run_"):
        rid = f"run_{rid.lstrip('v')}"

    report_path = backtest_report_path(rid, base_dir)
    if not report_path.is_file():
        raise FileNotFoundError(f"Backtest run not found: {rid}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    metrics_path = backtest_metrics_path(rid, base_dir)
    if metrics_path.is_file():
        report["metrics_file"] = json.loads(metrics_path.read_text(encoding="utf-8"))
    return report


def allocate_run_id(base_dir: str | Path | None = None) -> str:
    return next_backtest_run_id(base_dir)
