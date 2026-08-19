"""Daily engine supervisor report formatter (Phase 0 TIS)."""

from __future__ import annotations

from typing import Any


def format_daily_engine_report(report: dict[str, Any]) -> str:
    lines = [
        f"=== Daily Engine Report — {report.get('date', '')} ===",
        f"Generated: {report.get('generated_at', '')}",
        "",
    ]
    for engine, data in (report.get("engines") or {}).items():
        health = data.get("health") or {}
        lines.extend([
            f"--- {engine} ---",
            f"  Setups: {data.get('setups', 0)} | Trades: {data.get('trades', 0)} | "
            f"Rejections: {data.get('rejections', 0)}",
            f"  Win Rate: {data.get('win_rate_pct', 0)}% | PF: {data.get('pf', 0)} | "
            f"Expectancy: {data.get('expectancy_r', 0)}R | Max DD: {data.get('max_dd_r', 0)}R",
            f"  Health: enabled={health.get('enabled')} healthy={health.get('healthy')} | "
            f"24h signals={health.get('signals_generated_24h', 0)} "
            f"trades={health.get('trades_executed_24h', 0)}",
        ])
        top = data.get("top_rejection_reasons") or []
        if top:
            lines.append("  Top rejections: " + ", ".join(f"{r['reason']}({r['count']})" for r in top[:3]))
        lines.append("")

    alerts = report.get("alerts_24h") or []
    lines.append(f"--- Alerts (24h): {len(alerts)} ---")
    for a in alerts[-10:]:
        lines.append(f"  [{a.get('alert')}] {a.get('engine', a.get('symbol', ''))} @ {a.get('ts', '')}")
    if not alerts:
        lines.append("  (none)")
    return "\n".join(lines) + "\n"


def run_daily_engine_report(base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.services.engine_telemetry import get_engine_telemetry

    tel = get_engine_telemetry(base_dir)
    tel.update_engine_health()
    return tel.build_daily_report()
