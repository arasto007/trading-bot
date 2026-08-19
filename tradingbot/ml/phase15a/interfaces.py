"""Phase 15A — production provider interfaces (DI-friendly, no integration)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import pandas as pd

from tradingbot.ml.decision_engine.decision_types import FinalDecision, MarketContext
from tradingbot.ml.phase15a.unified_signal import UnifiedSignal


@runtime_checkable
class DecisionProvider(Protocol):
  def decide(self, context: MarketContext) -> FinalDecision: ...


@runtime_checkable
class CalibrationProvider(Protocol):
  def calibrate(self, raw_confidence: float, *, engine: str | None, regime: str) -> float: ...


@runtime_checkable
class RiskProvider(Protocol):
  def recommend(self, context: MarketContext, *, confidence: float, engine: str | None) -> dict[str, Any]: ...


@runtime_checkable
class QualityProvider(Protocol):
  def evaluate(self, context: MarketContext, *, confidence: float, risk: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class RouterProvider(Protocol):
  def route(self, context: MarketContext, row: pd.Series) -> dict[str, Any]: ...


@runtime_checkable
class SignalAssembler(Protocol):
  def assemble(
    self,
    *,
    decision: FinalDecision,
    calibrated_confidence: float,
    risk: dict[str, Any],
    quality: dict[str, Any],
    sl: float | None = None,
    tp: float | None = None,
  ) -> UnifiedSignal: ...
