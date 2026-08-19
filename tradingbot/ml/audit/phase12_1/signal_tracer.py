"""Phase 12.1 — signal decision path tracer (audit instrumentation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.integration.composite_registry import CompositeStrategyRegistry
from tradingbot.ml.integration.ml_strategy import STRATEGY_NAME


@dataclass
class SignalTrace:
    timestamp: str
    symbol: str
    final_signal: str
    signal_sources: list[dict[str, Any]] = field(default_factory=list)
    final_decision_source: str = "NONE"
    agreement: bool | None = None
    conflict: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "final_signal": self.final_signal,
            "signal_sources": self.signal_sources,
            "final_decision_source": self.final_decision_source,
            "agreement": self.agreement,
            "conflict": self.conflict,
        }


class SignalTracer:
    """
    Audit-only wrapper around CompositeStrategyRegistry.
    Does not modify production SignalStage — used for replay/trace analysis.
    """

    def __init__(self, registry: CompositeStrategyRegistry) -> None:
        self._registry = registry
        self.traces: list[SignalTrace] = []

    def trace_bar(
        self,
        market: MarketKey,
        df,
        *,
        timestamp: str,
    ) -> SignalTrace | None:
        import os

        os.environ.setdefault("ENABLE_ML_SHADOW", "true")

        ml_sig: TradingSignal | None = None
        rule_sig: TradingSignal | None = None

        try:
            ml_sig = self._registry._ml.generate_signal(market, df, None)
        except Exception:
            ml_sig = None

        try:
            rule_sig = self._registry._legacy.generate_signal(market, df, None)
        except Exception:
            rule_sig = None

        sources: list[dict[str, Any]] = []
        if ml_sig is not None:
            meta = ml_sig.metadata or {}
            sources.append(
                {
                    "name": "Phase9.9_ML",
                    "direction": ml_sig.direction.name,
                    "confidence": float(ml_sig.confidence),
                    "probability": meta.get("ml_probability"),
                }
            )
        else:
            sources.append({"name": "Phase9.9_ML", "direction": "HOLD", "confidence": 0.0})

        if rule_sig is not None:
            meta = rule_sig.metadata or {}
            sources.append(
                {
                    "name": rule_sig.strategy_name or "priceaction",
                    "direction": rule_sig.direction.name,
                    "confidence": float(rule_sig.confidence),
                    "pattern": meta.get("pattern") or meta.get("setup"),
                }
            )
        else:
            sources.append({"name": "priceaction", "direction": "HOLD", "confidence": 0.0})

        final = self._registry.generate_signal(market, df, None)
        final_dir = final.direction.name if final else "HOLD"
        source = _resolve_source(final, ml_sig, rule_sig)

        ml_dir = sources[0]["direction"]
        legacy_dir = sources[1]["direction"]
        agreement = (
            ml_dir == legacy_dir
            and ml_dir not in ("HOLD", "NONE")
            and legacy_dir not in ("HOLD", "NONE")
        )
        conflict = (
            ml_dir not in ("HOLD", "NONE")
            and legacy_dir not in ("HOLD", "NONE")
            and ml_dir != legacy_dir
        )

        trace = SignalTrace(
            timestamp=timestamp,
            symbol=market.symbol,
            final_signal=final_dir,
            signal_sources=sources,
            final_decision_source=source,
            agreement=agreement if final_dir != "HOLD" else None,
            conflict=conflict,
        )
        if final_dir != "HOLD":
            self.traces.append(trace)
        return trace


def _resolve_source(
    final: TradingSignal | None,
    ml_sig: TradingSignal | None,
    rule_sig: TradingSignal | None,
) -> str:
    if final is None:
        return "NONE"
    meta = final.metadata or {}
    if final.strategy_name == STRATEGY_NAME or meta.get("signal_source") == "ml_shadow":
        return "Phase9.9_ML"
    if meta.get("signal_source") == "rule_strategy":
        return rule_sig.strategy_name if rule_sig else "priceaction"
    if ml_sig is not None and ml_sig.direction not in (SignalDirection.HOLD,) and ml_sig.direction == final.direction:
        return "Phase9.9_ML"
    return final.strategy_name or "priceaction"


def build_signal_flow_report() -> dict[str, Any]:
    """Static documentation of production signal flow (from code analysis)."""
    return {
        "pipeline": [
            "Market Data (MT5 read-only / replay)",
            "TradingKernel.run_market_cycle",
            "DataStage → IndicatorsStage",
            "SignalStage.generate_signal(registry)",
            "RiskStage.evaluate",
            "ExecutionStage.execute (guarded in shadow/paper)",
        ],
        "signal_stage_entry": "tradingbot.pipeline.signal_stage.SignalStage",
        "registry_in_ml_path": "CompositeStrategyRegistry",
        "registry_in_legacy_live": "LegacyStrategyRegistry",
        "decision_mechanism": {
            "type": "ML_PRIORITY_OVERRIDE",
            "description": (
                "Both ML and legacy generate signals each bar. "
                "If ML returns non-HOLD, ML wins. "
                "Otherwise legacy priceaction is used. "
                "No weighted fusion or voting."
            ),
            "ml_weight": "100% when ML non-HOLD",
            "legacy_weight": "100% when ML HOLD/absent",
            "fusion": False,
        },
        "imported_strategies": ["MLShadowStrategy (Phase 9.9)", "LegacyStrategyRegistry → priceaction"],
        "instantiated_strategies": ["ml_shadow_phase9_9", "priceaction"],
        "executed_per_cycle": ["MLShadowStrategy.generate_signal", "LegacyStrategyRegistry.generate_signal"],
        "ignored_when_ml_wins": ["priceaction (computed but discarded)"],
    }
