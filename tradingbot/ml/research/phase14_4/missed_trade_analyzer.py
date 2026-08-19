"""Phase 14.4 — missed opportunity classification."""

from __future__ import annotations

from typing import Any


def classify_blocked_trade(record: dict[str, Any]) -> str:
    if record.get("allowed"):
        return "ACCEPTED"
    if record.get("raw_signal") not in ("BUY", "SELL"):
        return "CORRECT_REJECTION"

    r = float(record.get("r_multiple", 0.0))
    if r > 0.5:
        return "MISSED_WINNER"
    if r > 0:
        return "BAD_BLOCK"
    if r < -0.5:
        return "GOOD_BLOCK"
    return "CORRECT_REJECTION"


def analyze_missed_trades(records: list[dict[str, Any]]) -> dict[str, Any]:
    blocked = [r for r in records if not r["allowed"] and r["raw_signal"] in ("BUY", "SELL")]
    classified: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    for r in blocked:
        label = classify_blocked_trade(r)
        classified[label] = classified.get(label, 0) + 1
        if len(samples) < 100:
            samples.append(
                {
                    "timestamp": r.get("timestamp"),
                    "classification": label,
                    "decision_reason": r.get("decision_reason"),
                    "confidence": r["confidence"],
                    "risk_percent": r["risk_percent"],
                    "quality_score": r["quality_score"],
                    "block_reason": r.get("block_reason"),
                    "future_r_if_taken": r.get("r_multiple", 0.0),
                    "mfe": r.get("mfe", 0.0),
                    "mae": r.get("mae", 0.0),
                    "engine": r.get("engine"),
                    "regime": r.get("regime"),
                }
            )

    total_blocked = len(blocked)
    missed_winners = classified.get("MISSED_WINNER", 0) + classified.get("BAD_BLOCK", 0)
    good_blocks = classified.get("GOOD_BLOCK", 0) + classified.get("CORRECT_REJECTION", 0)

    return {
        "phase": "14.4",
        "total_blocked_signals": total_blocked,
        "classification_counts": classified,
        "missed_winner_rate": round(missed_winners / total_blocked, 4) if total_blocked else 0.0,
        "good_block_rate": round(good_blocks / total_blocked, 4) if total_blocked else 0.0,
        "samples": samples,
    }
