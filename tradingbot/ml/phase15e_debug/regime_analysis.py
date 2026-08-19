"""Phase 15E — regime activation heatmap."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.phase15e_debug.stage_probe import StageProbeResult


@dataclass
class RegimeActivationAnalyzer:
    probes: list[StageProbeResult] = field(default_factory=list)

    def build_report(self) -> dict[str, Any]:
        by_regime: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "bars": 0,
            "legacy_signals": 0,
            "decision_14_1_signals": 0,
            "calibrated_signals": 0,
            "kernel_signals": 0,
            "trading_signals": 0,
            "rejection_reasons": defaultdict(int),
        })

        regime_totals: dict[str, int] = defaultdict(int)
        for p in self.probes:
            regime_totals[p.regime] += 1
            cell = by_regime[p.regime]
            cell["bars"] += 1
            if p.legacy_signal in ("BUY", "SELL"):
                cell["legacy_signals"] += 1
            if p.decision_14_1_action in ("BUY", "SELL"):
                cell["decision_14_1_signals"] += 1
            if p.calibrated_action in ("BUY", "SELL"):
                cell["calibrated_signals"] += 1
            if p.kernel_final_action in ("BUY", "SELL"):
                cell["kernel_signals"] += 1
            if p.trading_signal in ("BUY", "SELL"):
                cell["trading_signals"] += 1
            if p.drop_reason:
                cell["rejection_reasons"][p.drop_stage] += 1

        total = len(self.probes) or 1
        distribution = {k: round(v / total, 4) for k, v in sorted(regime_totals.items())}

        heatmap: dict[str, Any] = {}
        for regime, cell in by_regime.items():
            bars = cell["bars"] or 1
            heatmap[regime] = {
                "bars": cell["bars"],
                "signal_density": round(cell["trading_signals"] / bars, 4),
                "legacy_density": round(cell["legacy_signals"] / bars, 4),
                "decision_density": round(cell["decision_14_1_signals"] / bars, 4),
                "acceptance_rate": round(cell["trading_signals"] / bars, 4),
                "calibrated_rate": round(cell["calibrated_signals"] / bars, 4),
                "rejection_reasons": dict(cell["rejection_reasons"]),
            }

        return {
            "regime_distribution": distribution,
            "TREND_pct": distribution.get("TREND", 0.0),
            "RANGE_pct": distribution.get("RANGE", 0.0),
            "HIGH_VOL_pct": distribution.get("HIGH_VOLATILITY", 0.0),
            "NO_TRADE_pct": distribution.get("NO_TRADE", 0.0),
            "heatmap": heatmap,
        }
