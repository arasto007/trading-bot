"""Phase 15C — signal performance statistics."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.monitoring.config import live_dir
from tradingbot.ml.monitoring.schema import PerformanceState, WindowMetrics
from tradingbot.ml.monitoring.statistics import rate

_SHADOW_WINDOWS = (500, 200, 50)


def snapshot_profit_factor(
    decisions: list[DecisionRecord],
    outcomes: dict[str, OutcomeRecord],
    *,
    window: int = 500,
) -> float:
    pairs = PerformanceMonitor._pairs(decisions, outcomes)[-window:]
    wins = sum(float(o.r_multiple) for _, o in pairs if o.r_multiple > 0)
    losses = abs(sum(float(o.r_multiple) for _, o in pairs if o.r_multiple < 0))
    if losses <= 0:
        return float(wins) if wins > 0 else 0.0
    return round(wins / losses, 4)


class PerformanceMonitor:
    """Aggregate signals/hour, direction mix, regime/engine share."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir
        self._decisions: list[dict[str, Any]] = []
        self._fallbacks = 0

    def ingest_decision(self, record: dict[str, Any]) -> None:
        self._decisions.append(record)

    def ingest_fallback(self) -> None:
        self._fallbacks += 1

    def build_report(self) -> dict[str, Any]:
        if not self._decisions:
            return {
                "signals_per_hour": 0.0,
                "buy": 0, "sell": 0, "hold": 0,
                "regime_pct": {}, "engine_pct": {},
                "fallback_pct": 0.0,
                "avg_confidence": 0.0, "avg_quality": 0.0, "avg_risk": 0.0,
            }

        directions = Counter(str(d.get("direction", "HOLD")) for d in self._decisions)
        regimes = Counter(str(d.get("regime", "UNKNOWN")) for d in self._decisions)
        engines = Counter(str(d.get("engine") or "none") for d in self._decisions)
        n = len(self._decisions)

        timestamps = []
        for d in self._decisions:
            try:
                timestamps.append(datetime.fromisoformat(str(d["timestamp"]).replace("Z", "+00:00")))
            except Exception:
                pass
        hours_span = 1.0
        if len(timestamps) >= 2:
            hours_span = max((timestamps[-1] - timestamps[0]).total_seconds() / 3600.0, 0.01)

        confidences = [float(d.get("confidence", 0)) for d in self._decisions]
        qualities = [float(d.get("quality", 0)) for d in self._decisions]
        risks = [float(d.get("risk", 0)) for d in self._decisions]

        return {
            "signals_per_hour": round(n / hours_span, 2),
            "buy": directions.get("BUY", 0),
            "sell": directions.get("SELL", 0),
            "hold": directions.get("HOLD", 0),
            "regime_pct": {k: rate(v, n) for k, v in regimes.items()},
            "engine_pct": {k: rate(v, n) for k, v in engines.items()},
            "fallback_pct": rate(self._fallbacks, n + self._fallbacks),
            "avg_confidence": round(sum(confidences) / n, 4),
            "avg_quality": round(sum(qualities) / n, 4),
            "avg_risk": round(sum(risks) / n, 4),
            "total_decisions": n,
            "total_fallbacks": self._fallbacks,
        }

    def write_report(self) -> Path:
        report = self.build_report()
        path = live_dir(self._base_dir) / "performance_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _pairs(
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> list[tuple[DecisionRecord, OutcomeRecord]]:
        pairs = [(d, outcomes[d.decision_id]) for d in decisions if d.decision_id in outcomes]
        pairs.sort(key=lambda item: item[0].timestamp)
        return pairs

    @classmethod
    def _window_metrics(cls, pairs: list[tuple[DecisionRecord, OutcomeRecord]], window: int) -> WindowMetrics:
        slice_pairs = pairs[-window:]
        samples = len(slice_pairs)
        if samples == 0:
            return WindowMetrics(
                window=window,
                expected_R=0.0,
                win_rate=0.0,
                max_drawdown=0.0,
                prediction_accuracy=0.0,
                calibration_error=0.0,
                samples=0,
                state=PerformanceState.WARNING.value,
            )

        trade_rs = [
            float(o.r_multiple)
            for d, o in slice_pairs
            if d.hybrid_decision in (DECISION_BUY, DECISION_SELL) and o.r_multiple != 0.0
        ]
        expected_r = float(np.mean(trade_rs)) if trade_rs else 0.0

        labeled = [(d, o) for d, o in slice_pairs if o.label in (0, 1)]
        win_rate = (
            float(sum(1 for _, o in labeled if o.r_multiple > 0) / len(labeled))
            if labeled
            else 0.0
        )

        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for _, o in slice_pairs:
            equity += float(o.r_multiple)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        if labeled:
            prediction_accuracy = float(
                sum(1 for d, o in labeled if d.ml_prediction == o.label) / len(labeled)
            )
            calibration_error = float(
                np.mean([abs(float(d.ml_probability) - float(o.label)) for d, o in labeled])
            )
        else:
            prediction_accuracy = 0.0
            calibration_error = 0.0

        state = PerformanceState.HEALTHY.value
        if expected_r < 0:
            state = PerformanceState.DEGRADED.value
        elif samples < 20:
            state = PerformanceState.WARNING.value

        return WindowMetrics(
            window=window,
            expected_R=round(expected_r, 4),
            win_rate=round(win_rate, 4),
            max_drawdown=round(max_drawdown, 4),
            prediction_accuracy=round(prediction_accuracy, 4),
            calibration_error=round(calibration_error, 4),
            samples=samples,
            state=state,
        )

    def latest_metrics(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
        *,
        window: int = 500,
    ) -> WindowMetrics:
        return self._window_metrics(self._pairs(decisions, outcomes), window)

    def compute_windows(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> list[WindowMetrics]:
        pairs = self._pairs(decisions, outcomes)
        return [self._window_metrics(pairs, window) for window in _SHADOW_WINDOWS]
