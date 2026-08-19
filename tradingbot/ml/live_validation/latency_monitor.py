"""Phase 15D — shadow replay latency monitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.monitoring.statistics import latency_summary, percentile


@dataclass
class ShadowLatencyMonitor:
    decision_ms: list[float] = field(default_factory=list)
    calibration_ms: list[float] = field(default_factory=list)
    risk_ms: list[float] = field(default_factory=list)
    quality_ms: list[float] = field(default_factory=list)
    adapter_ms: list[float] = field(default_factory=list)
    total_ms: list[float] = field(default_factory=list)

    def record_breakdown(self, breakdown: dict[str, float]) -> None:
        self.decision_ms.append(breakdown.get("decision_ms", 0.0))
        self.calibration_ms.append(breakdown.get("calibration_ms", 0.0))
        self.risk_ms.append(breakdown.get("risk_ms", 0.0))
        self.quality_ms.append(breakdown.get("quality_ms", 0.0))
        self.adapter_ms.append(breakdown.get("mapping_ms", 0.0))
        stage_total = (
            breakdown.get("decision_ms", 0.0)
            + breakdown.get("calibration_ms", 0.0)
            + breakdown.get("risk_ms", 0.0)
            + breakdown.get("quality_ms", 0.0)
            + breakdown.get("mapping_ms", 0.0)
        )
        if stage_total <= 0.0:
            stage_total = max(
                0.0,
                breakdown.get("total_ms", 0.0) - breakdown.get("features_ms", 0.0),
            )
        self.total_ms.append(stage_total)

    def build_report(self) -> dict[str, Any]:
        warm = self.total_ms[3:] if len(self.total_ms) > 3 else self.total_ms
        return {
            "decision": latency_summary(self.decision_ms),
            "calibration": latency_summary(self.calibration_ms),
            "risk": latency_summary(self.risk_ms),
            "quality": latency_summary(self.quality_ms),
            "kernel_adapter": latency_summary(self.adapter_ms),
            "total": latency_summary(self.total_ms),
            "warm_total": latency_summary(warm),
            "warm_p95_ms": round(percentile(warm, 0.95), 3) if warm else 0.0,
            "targets": {"mean_ms": 20.0, "p95_ms": 50.0},
        }

    def passes_targets(self) -> bool:
        warm = self.total_ms[3:] if len(self.total_ms) > 3 else self.total_ms
        if not warm:
            return False
        rep = latency_summary(warm)
        return rep["mean"] < 20.0 and percentile(warm, 0.95) < 50.0
