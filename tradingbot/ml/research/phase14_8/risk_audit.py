"""Phase 14.8 — risk layer audit."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_8.config import MAX_RISK_PERCENT


def audit_risk(records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [r for r in records if r.get("allowed")]
    risk_vals = [float(r.get("risk_percent", 0)) for r in records if r.get("raw_signal") in ("BUY", "SELL")]
    acc_risk = [float(r.get("risk_percent", 0)) for r in accepted]

    exceeds_cap = [v for v in risk_vals if v > MAX_RISK_PERCENT + 1e-9]
    negative = [v for v in risk_vals if v < 0]
    invalid_pct = [v for v in risk_vals if v > 1.0]

    blocked_risk = sum(1 for r in records if r.get("block_reason") == "risk")

    passes = (
        len(exceeds_cap) == 0
        and len(negative) == 0
        and len(invalid_pct) == 0
    )

    return {
        "phase": "14.8",
        "passes": passes,
        "max_risk_cap": MAX_RISK_PERCENT,
        "max_observed_risk": round(max(risk_vals), 6) if risk_vals else 0.0,
        "mean_risk_accepted": round(sum(acc_risk) / len(acc_risk), 6) if acc_risk else 0.0,
        "exceeds_cap_count": len(exceeds_cap),
        "negative_risk_count": len(negative),
        "invalid_percentage_count": len(invalid_pct),
        "blocked_by_risk": blocked_risk,
        "risk_traces_valid": passes,
        "scaling_errors": len(exceeds_cap) + len(invalid_pct),
    }
