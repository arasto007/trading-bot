"""Phase 15E — confidence distribution analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.confidence_engine.calibration_policy import MIN_CALIBRATED_CONFIDENCE
from tradingbot.ml.phase15e_debug.config import HISTOGRAM_BUCKETS, MIN_CONFIDENCE_THRESHOLD
from tradingbot.ml.phase15e_debug.stage_probe import StageProbeResult
from tradingbot.ml.trade_quality.quality_policy import QUALITY_THRESHOLD


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _histogram(values: list[float], buckets: int = HISTOGRAM_BUCKETS) -> list[dict[str, Any]]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [{"bin_start": lo, "bin_end": hi, "count": len(values)}]
    width = (hi - lo) / buckets
    counts = [0] * buckets
    for v in values:
        idx = min(buckets - 1, int((v - lo) / width) if width > 0 else 0)
        counts[idx] += 1
    out: list[dict[str, Any]] = []
    for i, c in enumerate(counts):
        start = lo + i * width
        end = lo + (i + 1) * width
        out.append({"bin_start": round(start, 4), "bin_end": round(end, 4), "count": c})
    return out


@dataclass
class ConfidenceAnalyzer:
    probes: list[StageProbeResult] = field(default_factory=list)

    def build_report(self) -> dict[str, Any]:
        raw = [p.raw_confidence for p in self.probes if p.unified_ok]
        calibrated = [p.calibrated_confidence for p in self.probes if p.unified_ok]
        d141 = [p.decision_14_1_confidence for p in self.probes if p.unified_ok]
        quality = [p.quality_score for p in self.probes if p.unified_ok]

        below_raw = sum(1 for v in raw if v < MIN_CONFIDENCE_THRESHOLD)
        below_cal = sum(1 for v in calibrated if v < MIN_CALIBRATED_CONFIDENCE)
        below_qual = sum(1 for v in quality if v < QUALITY_THRESHOLD)

        n = len(raw) or 1
        return {
            "mean_raw_confidence": _mean(raw),
            "mean_calibrated_confidence": _mean(calibrated),
            "mean_decision_14_1_confidence": _mean(d141),
            "mean_quality_score": _mean(quality),
            "pct_below_min_confidence_0_55": round(below_raw / n, 4),
            "pct_below_calibrated_threshold": round(below_cal / n, 4),
            "pct_below_quality_threshold_0_65": round(below_qual / n, 4),
            "thresholds": {
                "min_confidence": MIN_CONFIDENCE_THRESHOLD,
                "calibrated": MIN_CALIBRATED_CONFIDENCE,
                "quality_spec": QUALITY_THRESHOLD,
            },
            "raw_histogram": _histogram(raw),
            "calibrated_histogram": _histogram(calibrated),
            "quality_histogram": _histogram(quality),
        }
