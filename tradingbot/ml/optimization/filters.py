"""Adaptive session/regime filters from shadow performance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.optimization._sim import iter_pairs


SESSION_KEYS = ("london", "new_york", "asia")
REGIME_KEYS = ("trend", "range", "high_volatility", "low_volatility")


@dataclass
class FilterRecommendation:
    disable_session: str | None = None
    disable_regime: str | None = None
    disabled_sessions: list[str] = field(default_factory=list)
    disabled_regimes: list[str] = field(default_factory=list)
    reasons: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "disable_session": self.disable_session,
            "disable_regime": self.disable_regime,
            "disabled_sessions": self.disabled_sessions,
            "disabled_regimes": self.disabled_regimes,
            "reasons": self.reasons,
        }


@dataclass
class AdaptiveFilterAnalyzer:
    """Detect sessions/regimes with negative expected_R in shadow history."""

    min_samples: int = 5
    negative_r_threshold: float = 0.0

    def analyze(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> FilterRecommendation:
        pairs = iter_pairs(decisions, outcomes)
        rec = FilterRecommendation()

        session_rs = self._group_expected_r(pairs, lambda d: d.session, SESSION_KEYS)
        regime_rs = self._group_expected_r(pairs, lambda d: d.regime, REGIME_KEYS)

        for session, stats in session_rs.items():
            if stats["samples"] >= self.min_samples and stats["expected_R"] < self.negative_r_threshold:
                rec.disabled_sessions.append(session)
                rec.reasons.append(
                    {
                        "disable_session": session,
                        "reason": "negative expected_R",
                        "expected_R": str(stats["expected_R"]),
                    }
                )
                if rec.disable_session is None:
                    rec.disable_session = session

        for regime, stats in regime_rs.items():
            if stats["samples"] >= self.min_samples and stats["expected_R"] < self.negative_r_threshold:
                rec.disabled_regimes.append(regime)
                rec.reasons.append(
                    {
                        "disable_regime": regime,
                        "reason": "negative expected_R",
                        "expected_R": str(stats["expected_R"]),
                    }
                )
                if rec.disable_regime is None:
                    rec.disable_regime = regime

        return rec

    @staticmethod
    def _group_expected_r(pairs, key_fn, known_keys: tuple[str, ...]) -> dict[str, dict[str, float]]:
        buckets: dict[str, list[float]] = {k: [] for k in known_keys}
        for record, outcome in pairs:
            key = key_fn(record)
            if key not in buckets:
                continue
            if outcome.r_multiple == 0.0:
                continue
            buckets[key].append(outcome.r_multiple)

        out: dict[str, dict[str, float]] = {}
        for key, rs in buckets.items():
            if not rs:
                out[key] = {"expected_R": 0.0, "samples": 0.0}
            else:
                out[key] = {
                    "expected_R": round(float(np.mean(rs)), 4),
                    "samples": float(len(rs)),
                }
        return out
