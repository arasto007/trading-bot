"""Phase 14.6 — trade outcome vs confidence bucket alignment."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_6.config import CONFIDENCE_BUCKETS


def _bucket_label(lo: float, hi: float) -> str:
    return f"{lo:.1f}-{hi:.1f}"


def bucket_for_confidence(confidence: float) -> str:
    c = float(confidence)
    for lo, hi in CONFIDENCE_BUCKETS:
        if lo <= c < hi or (hi == 1.0 and c == 1.0):
            return _bucket_label(lo, hi)
    return _bucket_label(0.0, 0.2)


def analyze_label_alignment(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare calibrated confidence buckets to simulated trade outcomes."""
    buckets: dict[str, dict[str, Any]] = {}

    for rec in records:
        if rec.get("raw_signal") not in ("BUY", "SELL"):
            continue
        label = bucket_for_confidence(float(rec.get("confidence", 0)))
        buckets.setdefault(label, {"trades": 0, "wins": 0, "r_sum": 0.0, "loss_sum": 0.0, "win_sum": 0.0})
        r = float(rec.get("r_multiple", 0))
        b = buckets[label]
        b["trades"] += 1
        if r > 0:
            b["wins"] += 1
            b["win_sum"] += r
        elif r < 0:
            b["loss_sum"] += abs(r)
        b["r_sum"] += r

    rows: list[dict[str, Any]] = []
    for label in sorted(buckets.keys()):
        b = buckets[label]
        trades = b["trades"]
        wins = b["wins"]
        losses = trades - wins
        pf = b["win_sum"] / b["loss_sum"] if b["loss_sum"] > 0 else (2.0 if wins > 0 else 0.0)
        rows.append(
            {
                "bucket": label,
                "trades": trades,
                "win_rate": round(wins / trades, 4) if trades else 0.0,
                "profit_factor": round(pf, 4),
                "expectancy": round(b["r_sum"] / trades, 4) if trades else 0.0,
                "label_tp_before_sl_rate": round(wins / trades, 4) if trades else 0.0,
            }
        )

    monotonic = _check_monotonic_win_rate(rows)
    return {
        "phase": "14.6",
        "buckets": rows,
        "alignment_monotonic": monotonic,
        "calibration_quality": "good" if monotonic else "needs_improvement",
    }


def _check_monotonic_win_rate(rows: list[dict[str, Any]]) -> bool:
    rates = [r["win_rate"] for r in rows if r["trades"] >= 5]
    if len(rates) < 2:
        return True
    return rates == sorted(rates)
