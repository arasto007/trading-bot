"""Phase 15D — report generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.live_validation.config import reports_dir
from tradingbot.ml.live_validation.shadow_mode import ShadowModeResult


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase15d_reports(
    result: ShadowModeResult,
    *,
    base_dir: str | Path | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
) -> Path:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    shadow_stats = result.stats.build_report()
    shadow_equity = result.equity.build_report(result.stats.shadow_trades)
    signal_comparison = {
        "symbol": symbol,
        "timeframe": timeframe,
        **result.stats.decision_comparer.summary(),
        "records_sample": [r.to_dict() for r in result.stats.decision_comparer.records[:50]],
    }
    risk_comparison = {
        "symbol": symbol,
        **result.stats.risk_comparer.summary(),
        "records_sample": [r.to_dict() for r in result.stats.risk_comparer.records[:50]],
    }
    latency_report = result.latency.build_report()
    health_report = result.health.build_report()

    daily_summary = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "symbol": symbol,
        "bars_processed": shadow_stats.get("bars_processed", 0),
        "shadow_trades": shadow_stats.get("shadow_trades", 0),
        "agreement_rate": shadow_stats.get("agreement_rate", 0.0),
        "daily_pnl": shadow_equity.get("daily_pnl", {}),
        "order_send_calls": result.order_send_calls,
    }
    weekly_summary = {
        "week": datetime.now(timezone.utc).strftime("%Y-W%U"),
        "symbol": symbol,
        "weekly_pnl": shadow_equity.get("weekly_pnl", {}),
        "win_rate": shadow_equity.get("win_rate", 0.0),
        "profit_factor": shadow_equity.get("profit_factor", 0.0),
    }

    _write_json(out / "shadow_statistics.json", shadow_stats)
    _write_json(out / "shadow_equity.json", shadow_equity)
    _write_json(out / "signal_comparison.json", signal_comparison)
    _write_json(out / "risk_comparison.json", risk_comparison)
    _write_json(out / "latency_report.json", latency_report)
    _write_json(out / "health_report.json", health_report)
    _write_json(out / "daily_summary.json", daily_summary)
    _write_json(out / "weekly_summary.json", weekly_summary)
    return out


def write_final_report(
    payload: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
) -> Path:
    path = reports_dir(base_dir) / "phase15d_final_report.json"
    _write_json(path, payload)
    return path


REQUIRED_REPORTS = (
    "shadow_statistics.json",
    "shadow_equity.json",
    "signal_comparison.json",
    "risk_comparison.json",
    "latency_report.json",
    "health_report.json",
    "daily_summary.json",
    "weekly_summary.json",
    "phase15d_final_report.json",
)


def reports_complete(base_dir: str | Path | None = None) -> bool:
    out = reports_dir(base_dir)
    return all((out / name).is_file() for name in REQUIRED_REPORTS)
