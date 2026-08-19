"""Winner-Population Signal Quality Filter (WPSQF) — production service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.domain.models import TradingSignal
from tradingbot.services.signal_filter_log import log_rejection
from tradingbot.services.signal_filter_mode import resolve_wpsqf_threshold
from tradingbot.services.wpsqf_features import extract_entry_features
from tradingbot.services.wpsqf_scoring import false_signal_score, market_context_score, signal_quality_score


@dataclass(frozen=True)
class WpsqfResult:
    allowed: bool
    signal_quality_score: float
    false_signal_score: float
    market_context_score: float
    trend_aligned: bool
    threshold: float
    reject_reason: str | None = None
    features: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "signal_quality_score": self.signal_quality_score,
            "false_signal_score": self.false_signal_score,
            "market_context_score": self.market_context_score,
            "trend_aligned": self.trend_aligned,
            "threshold": self.threshold,
            "reject_reason": self.reject_reason,
        }


class WinnerPopulationSignalQualityFilter:
    """Phase 29A calibrated signal quality filter — deterministic, no ML retraining."""

    def __init__(self, *, threshold: float | None = None, config: dict | None = None) -> None:
        self._threshold = resolve_wpsqf_threshold(threshold, config=config)
        self._config = config or {}

    @property
    def threshold(self) -> float:
        return self._threshold

    def evaluate(
        self,
        signal: TradingSignal,
        closed_ohlcv: pd.DataFrame,
        *,
        timestamp: str | None = None,
        spread: float = 0.3,
    ) -> WpsqfResult:
        features = extract_entry_features(signal, closed_ohlcv, spread=spread)
        false_info = false_signal_score(features)
        ctx_info = market_context_score(features)
        features.update(false_info)
        features.update(ctx_info)

        score = signal_quality_score(features)
        allowed = score >= self._threshold
        reason = None if allowed else f"signal_quality_score {score:.2f} < threshold {self._threshold:.2f}"

        result = WpsqfResult(
            allowed=allowed,
            signal_quality_score=score,
            false_signal_score=float(false_info["false_signal_score"]),
            market_context_score=float(ctx_info["context_score"]),
            trend_aligned=bool(features.get("trend_aligned")),
            threshold=self._threshold,
            reject_reason=reason,
            features=features,
        )

        if not allowed:
            ts = timestamp or str(closed_ohlcv.index[-1])
            meta = signal.metadata or {}
            log_rejection(
                {
                    "timestamp": ts,
                    "symbol": signal.symbol,
                    "direction": signal.direction.name,
                    "ml_confidence": float(signal.confidence),
                    "signal_quality_score": score,
                    "false_signal_score": result.false_signal_score,
                    "market_context_score": result.market_context_score,
                    "trend_aligned": result.trend_aligned,
                    "reject_reason": reason,
                    "threshold": self._threshold,
                    "flags": false_info.get("flags", []),
                }
            )

        return result
