"""Phase 18A — shadow decision comparator (v40 vs v41)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShadowComparator:
    """Compare parallel v40 / v41 decisions without execution."""

    diffs: list[dict[str, Any]] = field(default_factory=list)
    agree: int = 0
    diverge: int = 0
    agree_by_regime: dict[str, int] = field(default_factory=lambda: {"TREND": 0, "RANGE": 0, "OTHER": 0})
    diverge_by_regime: dict[str, int] = field(default_factory=lambda: {"TREND": 0, "RANGE": 0, "OTHER": 0})

    def compare(
        self,
        *,
        bar_index: int,
        timestamp: str,
        regime: str,
        v40: dict[str, Any],
        v41: dict[str, Any],
        latency_v40_ms: float,
        latency_v41_ms: float,
    ) -> dict[str, Any]:
        sig40 = str(v40.get("signal", "HOLD"))
        sig41 = str(v41.get("signal", "HOLD"))
        agreed = sig40 == sig41
        key = regime if regime in ("TREND", "RANGE") else "OTHER"
        if agreed:
            self.agree += 1
            self.agree_by_regime[key] = self.agree_by_regime.get(key, 0) + 1
        else:
            self.diverge += 1
            self.diverge_by_regime[key] = self.diverge_by_regime.get(key, 0) + 1

        row = {
            "bar_index": bar_index,
            "timestamp": timestamp,
            "regime": regime,
            "v40_signal": sig40,
            "v41_signal": sig41,
            "v40_probability": float(v40.get("probability", 0.0)),
            "v41_probability": float(v41.get("probability", 0.0)),
            "v40_engine": v40.get("engine"),
            "v41_engine": v41.get("engine"),
            "agreed": agreed,
            "latency_v40_ms": round(latency_v40_ms, 4),
            "latency_v41_ms": round(latency_v41_ms, 4),
            "latency_delta_ms": round(latency_v41_ms - latency_v40_ms, 4),
        }
        if not agreed:
            self.diffs.append(row)
        return row

    def agreement_rate(self) -> float:
        total = self.agree + self.diverge
        return round(self.agree / total, 6) if total else 1.0

    def divergence_rate(self, regime: str | None = None) -> float:
        if regime is None:
            total = self.agree + self.diverge
            return round(self.diverge / total, 6) if total else 0.0
        a = self.agree_by_regime.get(regime, 0)
        d = self.diverge_by_regime.get(regime, 0)
        total = a + d
        return round(d / total, 6) if total else 0.0

    def decision_diff_report(self) -> dict[str, Any]:
        return {
            "phase": "18A",
            "total_compared": self.agree + self.diverge,
            "agree": self.agree,
            "diverge": self.diverge,
            "agreement_rate": self.agreement_rate(),
            "divergence_rate": self.divergence_rate(),
            "divergence_rate_trend": self.divergence_rate("TREND"),
            "divergence_rate_range": self.divergence_rate("RANGE"),
            "diffs": self.diffs,
        }

    def agreement_matrix(self) -> dict[str, Any]:
        matrix: dict[str, dict[str, int]] = {}
        for d in self.diffs:
            a = d["v40_signal"]
            b = d["v41_signal"]
            matrix.setdefault(a, {})
            matrix[a][b] = matrix[a].get(b, 0) + 1
        # include agreements as diagonal counts
        for sig in ("BUY", "SELL", "HOLD"):
            matrix.setdefault(sig, {})
            matrix[sig].setdefault(sig, 0)
        # reconstruct diagonal from totals (approx via non-diff is hard; store summary)
        return {
            "phase": "18A",
            "labels": ["BUY", "SELL", "HOLD"],
            "divergence_off_diagonal": matrix,
            "agree_counts": {
                "TREND": self.agree_by_regime.get("TREND", 0),
                "RANGE": self.agree_by_regime.get("RANGE", 0),
                "OTHER": self.agree_by_regime.get("OTHER", 0),
                "total": self.agree,
            },
            "diverge_counts": {
                "TREND": self.diverge_by_regime.get("TREND", 0),
                "RANGE": self.diverge_by_regime.get("RANGE", 0),
                "OTHER": self.diverge_by_regime.get("OTHER", 0),
                "total": self.diverge,
            },
            "agreement_rate": self.agreement_rate(),
        }
