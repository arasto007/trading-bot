"""Phase 14.7 — trade record tracking and enrichment."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_4.pipeline_simulator import simulate_trade_outcome


def build_trade_record(
    *,
    timestamp: str,
    year: int,
    pipeline: str,
    raw_signal: str,
    allowed: bool,
    block_reason: str | None,
    engine: str | None,
    regime: str,
    confidence: float,
    risk_percent: float = 0.0,
    quality_score: float = 0.0,
    r_multiple: float = 0.0,
    mfe: float = 0.0,
    mae: float = 0.0,
    raw_confidence: float | None = None,
    calibrated_confidence: float | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "year": year,
        "pipeline": pipeline,
        "raw_signal": raw_signal,
        "allowed": allowed,
        "block_reason": block_reason,
        "engine": engine,
        "regime": regime,
        "confidence": round(confidence, 6),
        "raw_confidence": round(raw_confidence, 6) if raw_confidence is not None else None,
        "calibrated_confidence": round(calibrated_confidence, 6) if calibrated_confidence is not None else None,
        "risk_percent": round(risk_percent, 6),
        "quality_score": round(quality_score, 6),
        "r_multiple": round(r_multiple, 4),
        "mfe": round(mfe, 4),
        "mae": round(mae, 4),
    }


def simulate_outcome(candles, bar_idx: int, direction: str) -> dict[str, float]:
    if direction not in ("BUY", "SELL"):
        return {"r_multiple": 0.0, "mfe": 0.0, "mae": 0.0}
    return simulate_trade_outcome(candles, bar_idx, direction=direction)


def accepted_trades(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r.get("allowed")]


def count_by_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        k = str(r.get(key) or "unknown")
        counts[k] = counts.get(k, 0) + 1
    return counts
