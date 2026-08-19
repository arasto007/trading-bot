"""Phase 9.10 — paper trading run persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    paper_trading_config_path,
    paper_trading_equity_path,
    paper_trading_metrics_path,
    paper_trading_report_path,
    paper_trading_run_dir,
    paper_trading_signals_path,
    paper_trading_state_path,
    paper_trading_trades_path,
)
from tradingbot.ml.paper_trading.performance_tracker import PerformanceMetrics, PerformanceTracker
from tradingbot.ml.paper_trading.position_manager import PositionManager


def save_run(
    run_id: str,
    *,
    manager: PositionManager,
    tracker: PerformanceTracker,
    metrics: PerformanceMetrics,
    config: dict[str, Any],
    signals: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    run_dir = paper_trading_run_dir(run_id, base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    trades = [t.to_dict() for t in manager.closed_trades]
    paper_trading_trades_path(run_id, base_dir).write_text(json.dumps(trades, indent=2), encoding="utf-8")
    paper_trading_equity_path(run_id, base_dir).write_text(json.dumps(tracker.equity_curve, indent=2), encoding="utf-8")
    paper_trading_metrics_path(run_id, base_dir).write_text(json.dumps(metrics.to_dict(), indent=2), encoding="utf-8")
    paper_trading_signals_path(run_id, base_dir).write_text(json.dumps(signals, indent=2), encoding="utf-8")
    paper_trading_config_path(run_id, base_dir).write_text(json.dumps(config, indent=2), encoding="utf-8")

    state = {
        "trade_counter": manager.trade_counter,
        "equity": tracker.equity,
        "last_signal_ts": manager.last_signal_ts,
        "open_position": manager.open_position.trade_id if manager.open_position else None,
    }
    paper_trading_state_path(run_id, base_dir).write_text(json.dumps(state, indent=2), encoding="utf-8")

    report = {
        "run_id": run_id,
        "phase": "9.10",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics.to_dict(),
        "config": config,
        "num_trades": len(trades),
        "num_signals": len(signals),
    }
    if extra:
        report.update(extra)

    paper_trading_report_path(run_id, base_dir).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "run_dir": run_dir,
        "trades": paper_trading_trades_path(run_id, base_dir),
        "equity_curve": paper_trading_equity_path(run_id, base_dir),
        "metrics": paper_trading_metrics_path(run_id, base_dir),
        "signals": paper_trading_signals_path(run_id, base_dir),
        "config": paper_trading_config_path(run_id, base_dir),
        "report": paper_trading_report_path(run_id, base_dir),
        "state": paper_trading_state_path(run_id, base_dir),
    }


def load_report(run_id: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    path = paper_trading_report_path(run_id, base_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Paper run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))
