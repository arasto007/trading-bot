"""Phase 20B — load Phase 20A live reports + certified live-path observation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase20b.config import OBSERVATION_DAYS, phase20a_reports_dir


def _load_json(path: Path) -> dict[str, Any] | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _records(payload: dict[str, Any] | list | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        recs = payload.get("records")
        if isinstance(recs, list):
            return [r for r in recs if isinstance(r, dict)]
    return []


def load_phase20a_live_reports(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = phase20a_reports_dir(base_dir)
    files = {
        "live_trades": root / "live_trades.json",
        "live_equity": root / "live_equity.json",
        "risk_events": root / "risk_events.json",
        "execution_log": root / "execution_log.json",
        "latency_live": root / "latency_live.json",
        "drawdown_live": root / "drawdown_live.json",
        "health_live": root / "health_live.json",
        "session_summary": root / "session_summary.json",
        "final_report": root / "phase20a_final_report.json",
    }
    loaded = {k: _load_json(p) for k, p in files.items()}
    trades = _records(loaded["live_trades"])
    executions = _records(loaded["execution_log"])
    latency = _records(loaded["latency_live"])
    equity = _records(loaded["live_equity"])
    drawdown = _records(loaded["drawdown_live"])
    risk_events = _records(loaded["risk_events"])
    health = _records(loaded["health_live"])

    return {
        "phase": "20B",
        "source": "phase20a_reports",
        "reports_dir": str(root),
        "files_present": {k: (files[k].is_file()) for k in files},
        "live_trades": trades,
        "executions": executions,
        "latency": latency,
        "equity": equity,
        "drawdown": drawdown,
        "risk_events": risk_events,
        "health": health,
        "session_summary": loaded.get("session_summary") or {},
        "final_report": loaded.get("final_report") or {},
        "broker_live_samples": len(trades) + len(executions) + len(latency),
    }


def collect_live_path_observation(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = OBSERVATION_DAYS,
    stride: int = 5,
) -> dict[str, Any]:
    """
    Observe the certified live production path (v41 + RSI/ADX filters).
    Simulation only — same stack as Phase 20A, no order_send.
    """
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.phase19a.backtest import run_production_backtest
    from tradingbot.ml.phase19c.backtest import run_filtered_backtest
    from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty or dataset is None or dataset.empty:
        return {
            "phase": "20B",
            "source": "live_path_observation",
            "available": False,
            "records": [],
            "baseline_records": [],
        }

    settings = ProfitabilityFilterSettings(
        enable_rsi=True,
        enable_adx=True,
        rsi_min=40.0,
        rsi_max=60.0,
        adx_min=15.0,
        adx_max=50.0,
    )
    filtered = run_filtered_backtest(
        candles,
        dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        days=days,
        stride=stride,
        filter_settings=settings,
    )
    baseline = run_production_backtest(
        candles,
        dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        days=days,
        stride=stride,
    )
    return {
        "phase": "20B",
        "source": "live_path_observation",
        "available": True,
        "days": days,
        "stride": stride,
        "filter_settings": settings.to_dict(),
        "records": filtered["records"],
        "baseline_records": baseline["records"],
        "filter_blocks": filtered.get("filter_blocks", 0),
        "bars_evaluated": filtered.get("bars_evaluated", 0),
    }


def merge_observation(
    live_reports: dict[str, Any],
    path_obs: dict[str, Any],
) -> dict[str, Any]:
    """Prefer broker live trades; fall back to live-path observation records."""
    broker_trades = live_reports.get("live_trades") or []
    obs_records = [r for r in (path_obs.get("records") or []) if r.get("allowed")]
    baseline = [r for r in (path_obs.get("baseline_records") or []) if r.get("allowed")]

    if broker_trades:
        trades = broker_trades
        data_source = "broker_live"
    else:
        trades = obs_records
        data_source = "live_path_observation"

    return {
        "phase": "20B",
        "data_source": data_source,
        "broker_live_samples": live_reports.get("broker_live_samples", 0),
        "trades": trades,
        "all_path_records": path_obs.get("records") or [],
        "baseline_trades": baseline,
        "executions": live_reports.get("executions") or [],
        "latency": live_reports.get("latency") or [],
        "equity": live_reports.get("equity") or [],
        "drawdown": live_reports.get("drawdown") or [],
        "risk_events": live_reports.get("risk_events") or [],
        "health": live_reports.get("health") or [],
        "filter_blocks": path_obs.get("filter_blocks", 0),
        "path_observation_available": bool(path_obs.get("available")),
    }
