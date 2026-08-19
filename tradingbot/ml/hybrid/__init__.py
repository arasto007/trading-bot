"""ML + rule hybrid decision layer — Phase 5.1 shadow mode."""

from __future__ import annotations

from tradingbot.ml.hybrid.config import HybridConfig
from tradingbot.ml.hybrid.conflict import WARNING_CONFLICT, resolve_conflict
from tradingbot.ml.hybrid.engine import HybridDecisionEngine, compute_confidence
from tradingbot.ml.hybrid.logger import HybridLogger
from tradingbot.ml.hybrid.ml_adapter import MLAdapter
from tradingbot.ml.hybrid.rules_adapter import RuleAdapter
from tradingbot.ml.hybrid.schema import HybridDecision, MLSignal, RuleSignal
from tradingbot.ml.hybrid.scoring import compute_final_score

__all__ = [
    "HybridConfig",
    "HybridDecision",
    "HybridDecisionEngine",
    "HybridLogger",
    "MLAdapter",
    "MLSignal",
    "RuleAdapter",
    "RuleSignal",
    "WARNING_CONFLICT",
    "compute_confidence",
    "compute_final_score",
    "resolve_conflict",
]
