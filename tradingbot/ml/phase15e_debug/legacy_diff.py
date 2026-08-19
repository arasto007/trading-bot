"""Phase 15E — ML vs legacy divergence analysis."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.phase15e_debug.stage_probe import StageProbeResult


@dataclass
class LegacyDiffEngine:
    probes: list[StageProbeResult] = field(default_factory=list)

    def build_report(self) -> dict[str, Any]:
        legacy_active = [p for p in self.probes if p.legacy_signal in ("BUY", "SELL")]
        ml_active = [p for p in self.probes if p.trading_signal in ("BUY", "SELL")]
        missing_ml = [p for p in legacy_active if p.trading_signal not in ("BUY", "SELL")]

        divergence_points = Counter()
        for p in missing_ml:
            if p.drop_stage:
                divergence_points[p.drop_stage] += 1
            elif p.regime in ("HIGH_VOLATILITY", "NO_TRADE"):
                divergence_points["regime_block"] += 1
            else:
                divergence_points["unknown"] += 1

        regime_mismatch_days: dict[str, int] = defaultdict(int)
        for p in missing_ml:
            day = p.timestamp[:10]
            regime_mismatch_days[day] += 1

        direction_conflict = sum(
            1 for p in self.probes
            if p.legacy_signal in ("BUY", "SELL")
            and p.trading_signal in ("BUY", "SELL")
            and p.legacy_signal != p.trading_signal
        )

        return {
            "legacy_signals": len(legacy_active),
            "ml_signals": len(ml_active),
            "missing_ml_when_legacy_active": len(missing_ml),
            "direction_conflicts": direction_conflict,
            "divergence_points": dict(divergence_points),
            "regime_mismatch_days": dict(sorted(regime_mismatch_days.items())),
            "sample_missing": [p.to_dict() for p in missing_ml[:25]],
            "feature_drift_suspected": sum(1 for p in self.probes if p.error == "unified_frame_empty"),
        }
