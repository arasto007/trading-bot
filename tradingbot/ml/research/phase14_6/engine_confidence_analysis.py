"""Phase 14.6 — per-engine confidence analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_6.confidence_distribution import distribution_stats, histogram
from tradingbot.ml.research.phase14_6.config import RANGE_ENGINE_ID, TREND_ENGINE_ID


def analyze_engine_confidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    engines: dict[str, dict[str, list[float]]] = {}

    for rec in records:
        eng = str(rec.get("engine") or "unknown")
        engines.setdefault(eng, {"model_raw": [], "phase14_1_raw": [], "calibrated": []})
        if rec.get("model_raw_confidence") is not None:
            engines[eng]["model_raw"].append(float(rec["model_raw_confidence"]))
        if rec.get("phase14_1_raw") is not None:
            engines[eng]["phase14_1_raw"].append(float(rec["phase14_1_raw"]))
        if rec.get("calibrated_confidence") is not None:
            engines[eng]["calibrated"].append(float(rec["calibrated_confidence"]))

    out: dict[str, Any] = {"phase": "14.6", "engines": {}}
    for eng, series in engines.items():
        out["engines"][eng] = {
            "model_raw": distribution_stats(series["model_raw"]),
            "phase14_1_raw": distribution_stats(series["phase14_1_raw"]),
            "calibrated": distribution_stats(series["calibrated"]),
            "histogram_calibrated": histogram(series["calibrated"]),
        }

    if RANGE_ENGINE_ID in out["engines"]:
        out["phase9_9_summary"] = out["engines"][RANGE_ENGINE_ID]
    if TREND_ENGINE_ID in out["engines"]:
        out["trend_rf_v40_summary"] = out["engines"][TREND_ENGINE_ID]

    return out
