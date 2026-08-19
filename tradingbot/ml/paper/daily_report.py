"""Phase 11 — paper trading report persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    paper_trading_config_path,
    paper_trading_cycles_path,
    paper_trading_daily_metrics_path,
    paper_trading_equity_path,
    paper_trading_final_report_path,
    paper_trading_integrity_report_path,
    paper_trading_risk_report_path,
    paper_trading_run_dir,
    paper_trading_session_metrics_path,
    paper_trading_trades_path,
)


def save_paper_run(
    run_id: str,
    *,
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    daily_metrics: list[dict[str, Any]],
    session_metrics: dict[str, Any],
    risk_report: dict[str, Any],
    integrity_report: dict[str, Any],
    final_report: dict[str, Any],
    config: dict[str, Any],
    cycles: list[dict[str, Any]] | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    root = paper_trading_run_dir(run_id, base_dir)
    root.mkdir(parents=True, exist_ok=True)

    paper_trading_trades_path(run_id, base_dir).write_text(json.dumps(trades, indent=2), encoding="utf-8")
    paper_trading_equity_path(run_id, base_dir).write_text(json.dumps(equity_curve, indent=2), encoding="utf-8")
    paper_trading_daily_metrics_path(run_id, base_dir).write_text(
        json.dumps(daily_metrics, indent=2), encoding="utf-8"
    )
    paper_trading_session_metrics_path(run_id, base_dir).write_text(
        json.dumps(session_metrics, indent=2), encoding="utf-8"
    )
    paper_trading_risk_report_path(run_id, base_dir).write_text(json.dumps(risk_report, indent=2), encoding="utf-8")
    paper_trading_integrity_report_path(run_id, base_dir).write_text(
        json.dumps(integrity_report, indent=2), encoding="utf-8"
    )
    paper_trading_final_report_path(run_id, base_dir).write_text(
        json.dumps(final_report, indent=2), encoding="utf-8"
    )
    paper_trading_config_path(run_id, base_dir).write_text(json.dumps(config, indent=2), encoding="utf-8")
    if cycles is not None:
        paper_trading_cycles_path(run_id, base_dir).write_text(json.dumps(cycles, indent=2), encoding="utf-8")

    return {
        "run_dir": root,
        "trades": paper_trading_trades_path(run_id, base_dir),
        "final_report": paper_trading_final_report_path(run_id, base_dir),
    }


def build_daily_metrics(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = {}
    for row in cycles:
        day = str(row.get("timestamp", ""))[:10]
        b = buckets.setdefault(day, {"cycles": 0, "ml_signals": 0, "risk_allowed": 0, "paper_actions": 0})
        b["cycles"] += 1
        if row.get("ml_signal") in ("BUY", "SELL"):
            b["ml_signals"] += 1
        if row.get("risk_allowed"):
            b["risk_allowed"] += 1
        if row.get("paper_action") == "OPEN":
            b["paper_actions"] += 1
    return [{"date": day, **vals} for day, vals in sorted(buckets.items())]
