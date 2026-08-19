"""Decision memory schema — shadow performance tracking."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL, HybridDecision


def new_decision_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DecisionRecord:
    decision_id: str
    timestamp: str
    symbol: str
    timeframe: str
    model_name: str
    ml_probability: float
    ml_prediction: int
    rule_signal: str
    hybrid_decision: str
    confidence: str
    final_score: float
    features_version: str
    dataset_version: str
    entry_price: float = 0.0
    direction: int = 0
    session: str = "unknown"
    regime: str = "unknown"
    features_snapshot: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionRecord":
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields if k in data})

    @classmethod
    def from_hybrid(
        cls,
        hybrid: HybridDecision | dict[str, Any],
        *,
        model_name: str,
        features_version: str = "2.0",
        dataset_version: str = "1.0",
        entry_price: float = 0.0,
        direction: int = 0,
        session: str = "unknown",
        regime: str = "unknown",
        features_snapshot: dict[str, float] | None = None,
        decision_id: str | None = None,
    ) -> "DecisionRecord":
        data = hybrid.to_dict() if isinstance(hybrid, HybridDecision) else dict(hybrid)
        return cls(
            decision_id=decision_id or new_decision_id(),
            timestamp=str(data.get("timestamp", utc_now_iso())),
            symbol=str(data.get("symbol", "XAUUSD")).upper(),
            timeframe=str(data.get("timeframe", "M5")).upper(),
            model_name=model_name,
            ml_probability=float(data.get("ml_probability", 0.0)),
            ml_prediction=int(data.get("ml_prediction", 0)),
            rule_signal=str(data.get("rule_signal", "WAIT")),
            hybrid_decision=str(data.get("decision", "WAIT")),
            confidence=str(data.get("confidence", "LOW")),
            final_score=float(data.get("final_score", 0.0)),
            features_version=features_version,
            dataset_version=dataset_version,
            entry_price=float(entry_price),
            direction=int(direction),
            session=session,
            regime=regime,
            features_snapshot=features_snapshot or {},
        )


@dataclass
class OutcomeRecord:
    decision_id: str
    evaluated_at: str
    future_return: float
    tp_hit: bool
    sl_hit: bool
    max_favorable_excursion: float
    max_adverse_excursion: float
    r_multiple: float
    label: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutcomeRecord":
        return cls(
            decision_id=data["decision_id"],
            evaluated_at=data.get("evaluated_at", utc_now_iso()),
            future_return=float(data.get("future_return", 0.0)),
            tp_hit=bool(data.get("tp_hit", False)),
            sl_hit=bool(data.get("sl_hit", False)),
            max_favorable_excursion=float(
                data.get("max_favorable_excursion", data.get("mfe", 0.0))
            ),
            max_adverse_excursion=float(
                data.get("max_adverse_excursion", data.get("mae", 0.0))
            ),
            r_multiple=float(data.get("r_multiple", 0.0)),
            label=int(data.get("label", -1)),
        )


def direction_from_decision(decision: str, fallback: int = 0) -> int:
    d = decision.upper()
    if d == DECISION_BUY:
        return 1
    if d == DECISION_SELL:
        return -1
    return fallback


def session_from_features(features: dict[str, Any]) -> str:
    if float(features.get("session_london", 0)) >= 0.5:
        return "london"
    if float(features.get("session_ny", 0)) >= 0.5:
        return "new_york"
    if float(features.get("session_asia", 0)) >= 0.5:
        return "asia"
    return "unknown"


def regime_from_features(features: dict[str, Any]) -> str:
    trend = float(features.get("trend_strength", 0.0))
    vol = float(features.get("volatility_regime", 0.5))
    atr_pct = float(features.get("atr_percentile", 50.0))
    if vol >= 0.75 or atr_pct > 70:
        return "high_volatility"
    if vol <= 0.25 or atr_pct < 30:
        return "low_volatility"
    if trend >= 25:
        return "trend"
    return "range"
