"""ML decision layer — Phase 5.0 shadow mode (offline only)."""

from __future__ import annotations

from tradingbot.ml.decision.confidence import ConfidenceConfig, confidence_from_probability
from tradingbot.ml.decision.explain import explain_decision
from tradingbot.ml.decision.logger import DecisionLogger
from tradingbot.ml.decision.policy import DecisionPolicy, PolicyResult
from tradingbot.ml.decision.predictor import MLPredictor
from tradingbot.ml.decision.schema import MLDecision
from tradingbot.ml.decision.shadow import ShadowEngine, ShadowRecord

__all__ = [
    "ConfidenceConfig",
    "DecisionLogger",
    "DecisionPolicy",
    "MLDecision",
    "MLPredictor",
    "PolicyResult",
    "ShadowEngine",
    "ShadowRecord",
    "confidence_from_probability",
    "explain_decision",
]
