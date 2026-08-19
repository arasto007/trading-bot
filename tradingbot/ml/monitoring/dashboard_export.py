"""Phase 15C — consolidated dashboard and alert generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.monitoring.config import (
    CONFIDENCE_COLLAPSE_THRESHOLD,
    FALLBACK_RATE_ALERT,
    LATENCY_ALERT_MS,
    live_dir,
)


def generate_alerts(
    *,
    latency_report: dict[str, Any],
    health_status: dict[str, Any],
    fallback_report: dict[str, Any],
    performance: dict[str, Any],
    prediction_stats: dict[str, Any],
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    total_inf = latency_report.get("total_inference", {})
    if total_inf.get("max", 0) > LATENCY_ALERT_MS:
        alerts.append({
            "severity": "warning",
            "code": "LATENCY_HIGH",
            "detail": f"Max latency {total_inf.get('max')}ms > {LATENCY_ALERT_MS}ms",
        })
    if total_inf.get("p95", 0) > LATENCY_ALERT_MS:
        alerts.append({
            "severity": "warning",
            "code": "LATENCY_P95_HIGH",
            "detail": f"P95 latency {total_inf.get('p95')}ms > {LATENCY_ALERT_MS}ms",
        })

    bundles = health_status.get("bundles", {})
    if not bundles.get("all_valid"):
        alerts.append({"severity": "critical", "code": "BUNDLE_INVALID", "detail": "Bundle checksum or integrity failed"})
    if not health_status.get("fingerprint_match", True):
        alerts.append({"severity": "critical", "code": "FINGERPRINT_MISMATCH", "detail": "Dataset fingerprint mismatch"})

    if fallback_report.get("fallback_rate", 0) > FALLBACK_RATE_ALERT:
        alerts.append({
            "severity": "warning",
            "code": "FALLBACK_RATE_HIGH",
            "detail": f"Fallback rate {fallback_report.get('fallback_rate')} > {FALLBACK_RATE_ALERT}",
        })

    mean_conf = prediction_stats.get("mean_confidence", 1.0)
    if mean_conf < CONFIDENCE_COLLAPSE_THRESHOLD and prediction_stats.get("total_predictions", 0) > 10:
        alerts.append({
            "severity": "warning",
            "code": "CONFIDENCE_COLLAPSE",
            "detail": f"Mean confidence {mean_conf} < {CONFIDENCE_COLLAPSE_THRESHOLD}",
        })

    if performance.get("buy", 0) + performance.get("sell", 0) == 0 and performance.get("total_decisions", 0) > 50:
        alerts.append({"severity": "info", "code": "NO_TRADE_SIGNALS", "detail": "No BUY/SELL signals in window"})

    for eid, eng in health_status.get("engine_availability", {}).items():
        if eng.get("status") not in ("OK", None):
            alerts.append({
                "severity": "critical",
                "code": "ENGINE_UNAVAILABLE",
                "detail": f"Engine {eid} status {eng.get('status')}",
            })

    gate_errors = health_status.get("gate_errors", [])
    if any("feature" in e for e in gate_errors):
        alerts.append({"severity": "critical", "code": "FEATURE_MISMATCH", "detail": ";".join(gate_errors[:3])})

    return alerts


class DashboardExport:
    """Produce consolidated dashboard.json."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir
        self._path = live_dir(base_dir) / "dashboard.json"

    def build(
        self,
        *,
        health_status: dict[str, Any],
        latency_report: dict[str, Any],
        engine_report: dict[str, Any],
        fallback_report: dict[str, Any],
        prediction_stats: dict[str, Any],
        performance: dict[str, Any],
        recent_decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        alerts = generate_alerts(
            latency_report=latency_report,
            health_status=health_status,
            fallback_report=fallback_report,
            performance=performance,
            prediction_stats=prediction_stats,
        )
        return {
            "phase": "15C",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "live_status": "healthy" if health_status.get("passes") and not alerts else "degraded",
            "health": health_status,
            "latency": latency_report,
            "engine_health": engine_report,
            "signal_statistics": prediction_stats,
            "performance": performance,
            "fallback": fallback_report,
            "recent_decisions": recent_decisions[-20:],
            "alerts": alerts,
        }

    def write(self, payload: dict[str, Any]) -> Path:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self._path
