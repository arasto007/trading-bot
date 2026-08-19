"""Phase 14.1 — engine selection by regime."""

from __future__ import annotations

from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID
from tradingbot.ml.decision_engine.decision_types import EngineSignal, MarketContext

BLOCKED_REGIMES = frozenset({"HIGH_VOLATILITY", "NO_TRADE"})
VOL_REGIME_ENGINE = "vol_regime"


def _active_trend_engine_id() -> str:
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    return resolve_active_trend_engine_id()


def select_engine(regime: str) -> str | None:
    """Return engine model id for regime, or None when trading is blocked."""
    regime = str(regime).upper()
    if regime == "RANGE":
        return RANGE_MODEL_ID
    if regime == "TREND":
        return _active_trend_engine_id()
    if regime in BLOCKED_REGIMES:
        return None
    return None


def select_signal(context: MarketContext, engine_id: str | None) -> EngineSignal | None:
    if engine_id is None:
        return None
    if engine_id == VOL_REGIME_ENGINE:
        direction = int(context.features.get("vol_regime_direction", 0))
        if direction not in (1, -1):
            return None
        action = "BUY" if direction > 0 else "SELL"
        from tradingbot.ml.decision_engine.decision_policy import VOL_REGIME_RULE_CONFIDENCE

        return EngineSignal(
            signal=action,  # type: ignore[arg-type]
            confidence=VOL_REGIME_RULE_CONFIDENCE,
            model=VOL_REGIME_ENGINE,
            metadata={"ml_filter": "SKIP", "rule_only": True},
        )
    if engine_id == RANGE_MODEL_ID:
        return context.range_signal
    if engine_id == _active_trend_engine_id():
        return context.trend_signal
    return None


def routing_action(regime: str) -> str:
    """Human-readable routing outcome for traces."""
    regime = str(regime).upper()
    if regime == "RANGE":
        return f"route_to_{RANGE_MODEL_ID}"
    if regime == "TREND":
        return f"route_to_{_active_trend_engine_id()}"
    if regime in BLOCKED_REGIMES:
        return "BLOCK"
    return "BLOCK"
