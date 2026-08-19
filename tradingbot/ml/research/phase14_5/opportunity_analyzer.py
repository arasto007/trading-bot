"""Phase 14.5 — rejected opportunity classification."""

from __future__ import annotations

from typing import Any


def classify_opportunity(record: dict[str, Any]) -> str:
    if record.get("allowed"):
        conf = float(record.get("confidence", 0))
        r = float(record.get("r_multiple", 0))
        if conf >= 0.65 and r < 0:
            return "high_confidence_loser"
        if conf < 0.55 and r > 0:
            return "low_confidence_winner"
        return "ACCEPTED"
    if record.get("raw_signal") not in ("BUY", "SELL"):
        return "correct_rejection"
    r = float(record.get("r_multiple", 0))
    if r > 0.5:
        return "false_rejection"
    if r < -0.5:
        return "correct_rejection"
    if r > 0:
        return "low_confidence_winner"
    return "correct_rejection"


def analyze_opportunities(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    for r in records:
        label = classify_opportunity(r)
        counts[label] = counts.get(label, 0) + 1
        if label in ("false_rejection", "low_confidence_winner", "high_confidence_loser") and len(samples) < 150:
            samples.append(
                {
                    "timestamp": r.get("timestamp"),
                    "classification": label,
                    "confidence": r.get("confidence"),
                    "regime": r.get("regime"),
                    "block_reason": r.get("block_reason"),
                    "r_multiple": r.get("r_multiple"),
                    "allowed": r.get("allowed"),
                }
            )

    blocked_signals = [r for r in records if not r.get("allowed") and r.get("raw_signal") in ("BUY", "SELL")]
    false_rej = counts.get("false_rejection", 0) + counts.get("low_confidence_winner", 0)

    return {
        "phase": "14.5",
        "classification_counts": counts,
        "false_rejections": counts.get("false_rejection", 0),
        "correct_rejections": counts.get("correct_rejection", 0),
        "low_confidence_winners": counts.get("low_confidence_winner", 0),
        "high_confidence_losers": counts.get("high_confidence_loser", 0),
        "false_rejection_rate": round(false_rej / len(blocked_signals), 4) if blocked_signals else 0.0,
        "samples": samples,
    }
