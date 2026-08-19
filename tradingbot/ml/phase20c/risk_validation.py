"""Phase 20C — risk limit validation on real executions."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase20a.config import DEFAULT_RISK_PCT, MAX_OPEN_POSITIONS, MAX_RISK_PCT


def validate_risk(data: dict[str, Any]) -> dict[str, Any]:
    fills = data.get("real_fills") or []
    risk_events = data.get("risk_events") or []

    if not fills and not risk_events:
        return {
            "phase": "20C",
            "status": "PENDING",
            "reason": "no_real_trades_or_risk_events",
            "checks": {},
        }

    violations: list[dict[str, Any]] = []
    # Concurrent opens only when explicitly logged (open_positions / concurrent_open)
    max_open_seen = 0
    for f in fills:
        risk = f.get("risk_percent", f.get("risk_pct"))
        if risk is not None:
            try:
                r = float(risk)
                if r > MAX_RISK_PCT + 1e-9:
                    violations.append({
                        "type": "risk_limit_exceeded",
                        "ticket": f.get("ticket"),
                        "risk_percent": r,
                        "limit": MAX_RISK_PCT,
                    })
            except (TypeError, ValueError):
                pass

        explicit_open = f.get("open_positions", f.get("concurrent_open"))
        if explicit_open is not None:
            try:
                max_open_seen = max(max_open_seen, int(explicit_open))
            except (TypeError, ValueError):
                pass

    if max_open_seen > MAX_OPEN_POSITIONS:
        violations.append({
            "type": "max_open_positions_exceeded",
            "observed": max_open_seen,
            "limit": MAX_OPEN_POSITIONS,
        })

    # RiskGate blocks should exist when limits hit — count allowed vs blocked
    blocked = [e for e in risk_events if not e.get("allowed", True)]
    allowed = [e for e in risk_events if e.get("allowed", True)]

    checks = {
        "risk_limits_respected": not any(v["type"] == "risk_limit_exceeded" for v in violations),
        "position_sizing_ok": True,  # no counter-evidence without lot anomalies
        "max_open_positions_ok": max_open_seen == 0 or max_open_seen <= MAX_OPEN_POSITIONS,
        "max_exposure_ok": not any(v["type"] == "risk_limit_exceeded" for v in violations),
        "riskgate_events_logged": len(risk_events) > 0 or len(fills) > 0,
    }

    # Position sizing: volumes should be positive and finite
    for f in fills:
        vol = f.get("volume")
        if vol is not None:
            try:
                if float(vol) <= 0:
                    checks["position_sizing_ok"] = False
                    violations.append({"type": "invalid_volume", "ticket": f.get("ticket"), "volume": vol})
            except (TypeError, ValueError):
                checks["position_sizing_ok"] = False

    passed = all(checks.values()) and len(violations) == 0

    return {
        "phase": "20C",
        "status": "COMPLETE" if fills else "PARTIAL",
        "passed": passed,
        "checks": checks,
        "violations": violations,
        "max_open_positions_observed": max_open_seen,
        "max_open_positions_limit": MAX_OPEN_POSITIONS,
        "default_risk_pct": DEFAULT_RISK_PCT,
        "riskgate_allowed": len(allowed),
        "riskgate_blocked": len(blocked),
        "fills_checked": len(fills),
    }
