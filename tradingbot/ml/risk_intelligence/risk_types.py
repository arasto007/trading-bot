"""Phase 14.2B — adaptive risk typed structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tradingbot.ml.decision_engine.decision_types import MarketContext


@dataclass(frozen=True)
class AccountState:
    """Simulated or live account snapshot for risk intelligence."""

    equity: float = 10_000.0
    balance: float = 10_000.0
    peak_equity: float = 10_000.0
    open_positions: int = 0
    daily_pnl_pct: float = 0.0

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "equity": round(self.equity, 2),
            "balance": round(self.balance, 2),
            "peak_equity": round(self.peak_equity, 2),
            "drawdown_pct": round(self.drawdown_pct, 4),
            "open_positions": self.open_positions,
            "daily_pnl_pct": round(self.daily_pnl_pct, 4),
        }


@dataclass(frozen=True)
class HistoricalMetrics:
    """Frozen engine quality references — not retrained in this phase."""

    phase99_pf: float = 1.06
    trend_rf_pf: float = 1.21
    trend_wf_robustness: float = 0.83
    engine_trade_count: dict[str, int] = field(default_factory=dict)

    def engine_quality_factor(self, engine: str | None) -> float:
        if engine == "phase9_9":
            return min(1.2, self.phase99_pf / 1.0)
        if engine == "trend_rf_v40":
            return min(1.3, (self.trend_rf_pf / 1.2) * (0.5 + 0.5 * self.trend_wf_robustness))
        return 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase99_pf": self.phase99_pf,
            "trend_rf_pf": self.trend_rf_pf,
            "trend_wf_robustness": self.trend_wf_robustness,
            "engine_trade_count": dict(self.engine_trade_count),
        }


@dataclass
class AdaptiveRiskContext:
    """Inputs for adaptive risk calculation."""

    market: MarketContext
    calibrated_confidence: float
    action: str
    engine: str | None
    regime: str
    atr_percentile: float
    session: str
    account: AccountState
    history: HistoricalMetrics
    timestamp: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.market.symbol,
            "timeframe": self.market.timeframe,
            "action": self.action,
            "engine": self.engine,
            "regime": self.regime,
            "calibrated_confidence": round(self.calibrated_confidence, 6),
            "atr_percentile": round(self.atr_percentile, 4),
            "session": self.session,
            "account": self.account.to_dict(),
            "history": self.history.to_dict(),
            "timestamp": (self.timestamp or self.market.timestamp).isoformat()
            if (self.timestamp or self.market.timestamp)
            else None,
        }


@dataclass
class RiskRecommendation:
    """Adaptive risk recommendation — RiskGate remains final authority."""

    allowed: bool
    risk_percent: float
    multiplier: float
    confidence_factor: float
    regime_factor: float
    volatility_factor: float
    session_factor: float
    drawdown_factor: float
    engine_factor: float = 1.0
    reason: str = ""
    trace: list[str] = field(default_factory=list)
    blocked_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk_percent": round(self.risk_percent, 4),
            "multiplier": round(self.multiplier, 4),
            "confidence_factor": round(self.confidence_factor, 4),
            "regime_factor": round(self.regime_factor, 4),
            "volatility_factor": round(self.volatility_factor, 4),
            "session_factor": round(self.session_factor, 4),
            "drawdown_factor": round(self.drawdown_factor, 4),
            "engine_factor": round(self.engine_factor, 4),
            "reason": self.reason,
            "trace": self.trace,
            "blocked_by": self.blocked_by,
        }
