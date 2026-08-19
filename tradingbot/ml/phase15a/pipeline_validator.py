"""Phase 15A — ML pipeline validator (no execution)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, validate_routing
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.interfaces import (
    CalibrationProvider,
    DecisionProvider,
    QualityProvider,
    RiskProvider,
    RouterProvider,
)
from tradingbot.ml.phase15a.unified_signal import UnifiedSignal, SIGNAL_SCHEMA
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame


class _StubCalibration:
    def calibrate(self, raw_confidence: float, *, engine: str | None, regime: str) -> float:
        return raw_confidence


class _StubRisk:
    def recommend(self, context, *, confidence: float, engine: str | None) -> dict[str, Any]:
        return {"allowed": True, "risk_percent": 0.25}


class _StubQuality:
    def evaluate(self, context, *, confidence: float, risk: dict[str, Any]) -> dict[str, Any]:
        return {"allowed": True, "score": 0.7}


def _validate_interfaces() -> dict[str, Any]:
    checks = {
        "DecisionProvider": isinstance(DecisionOrchestrator(), DecisionProvider),
        "CalibrationProvider": isinstance(_StubCalibration(), CalibrationProvider),
        "RiskProvider": isinstance(_StubRisk(), RiskProvider),
        "QualityProvider": isinstance(_StubQuality(), QualityProvider),
    }
    return {"interface_checks": checks, "passes": all(checks.values())}


def validate_pipeline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    registry: EngineRegistry | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    sample_bars: int = 5,
) -> dict[str, Any]:
    reg = registry or EngineRegistry.build_default(build_trend_if_missing=True, symbol=symbol)
    routing = validate_routing()
    iface = _validate_interfaces()

    unified = build_unified_frame(candles, dataset)
    if unified.empty:
        return {"passes": False, "error": "empty_unified_frame"}

    range_eng = reg.get("phase9_9")
    trend_eng = reg.get("trend_rf_v40")
    if range_eng is None or trend_eng is None:
        return {"passes": False, "error": "engines_missing"}

    trend_inner = getattr(trend_eng, "inner", None)
    range_inner = getattr(range_eng, "inner", None)
    if trend_inner is None or range_inner is None:
        return {"passes": False, "error": "engine_inner_missing"}

    orchestrator = DecisionOrchestrator()
    signals: list[dict[str, Any]] = []
    schema_errors: list[str] = []

    stride = max(1, len(unified) // sample_bars)
    for i in range(0, min(len(unified), sample_bars * stride), stride):
        row = unified.iloc[i]
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_inner, trend_engine=trend_inner,
        )
        decision = orchestrator.decide(ctx)
        cal = _StubCalibration().calibrate(decision.confidence, engine=decision.engine, regime=decision.regime)
        risk = _StubRisk().recommend(ctx, confidence=cal, engine=decision.engine)
        quality = _StubQuality().evaluate(ctx, confidence=cal, risk=risk)
        sig = UnifiedSignal(
            engine=decision.engine,
            regime=decision.regime,
            direction=decision.action,
            confidence=cal,
            quality=float(quality.get("score", 0)),
            risk=float(risk.get("risk_percent", 0)),
            reason=list(decision.explanation),
            trace=list(decision.trace),
        )
        errs = sig.validate_schema()
        if errs:
            schema_errors.extend(errs)
        signals.append(sig.to_dict())

    passes = routing.get("passes", False) and iface.get("passes", False) and not schema_errors
    return {
        "phase": "15A",
        "routing": routing,
        "interfaces": iface,
        "signal_schema": SIGNAL_SCHEMA,
        "sample_signals": signals,
        "schema_errors": schema_errors,
        "engines_registered": reg.list_ids(),
        "passes": passes,
    }
