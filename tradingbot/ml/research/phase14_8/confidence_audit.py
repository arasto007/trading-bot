"""Phase 14.8 — confidence distribution audit."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_6.confidence_distribution import distribution_stats


def audit_confidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [r for r in records if r.get("allowed")]
    all_conf = [float(r["confidence"]) for r in records if r.get("raw_signal") in ("BUY", "SELL")]
    acc_conf = [float(r["confidence"]) for r in accepted]
    raw_conf = [float(r["raw_confidence"]) for r in accepted if r.get("raw_confidence") is not None]

    return {
        "phase": "14.8",
        "signal_confidence": distribution_stats(all_conf),
        "accepted_confidence": distribution_stats(acc_conf),
        "raw_confidence_accepted": distribution_stats(raw_conf),
        "compression_detected": distribution_stats(acc_conf).get("p90", 1.0) < 0.20,
        "calibration_spread_ok": distribution_stats(acc_conf).get("spread_p90_p10", 0) >= 0.15,
    }
