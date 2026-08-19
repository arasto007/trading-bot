"""Phase 15B — ML kernel adapter (signal generation only, no execution)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.confidence_engine.validator import CalibratedDecisionAdapter
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.integration.health_gate import KernelFallbackError, require_health
from tradingbot.ml.integration.monitoring import (
    log_decision_latency,
    log_kernel_decision,
    write_engine_health,
)
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id
from tradingbot.ml.phase19c.filters import apply_profitability_filters
from tradingbot.ml.integration.regime_filter_profiles import (
    FilterProfileDiagnostics,
    attach_filter_diagnostics,
    select_profitability_filter_settings,
)
from tradingbot.ml.integration.signal_mapper import map_unified_to_trading_signal
from tradingbot.ml.research.phase22c.hold_chain import HoldStage, get_hold_chain, hold_chain_enabled
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.unified_signal import UnifiedSignal
from tradingbot.ml.risk_intelligence.validator import AdaptiveRiskAdapter
from tradingbot.ml.trade_quality.adapter import TradeQualityAdapter

logger = logging.getLogger(__name__)

PIPELINE_TIMEOUT_MS = 500.0
LATENCY_TARGET_MS = 50.0


@dataclass
class MLKernelDependencies:
    registry: EngineRegistry
    orchestrator: DecisionOrchestrator
    calibration: CalibratedDecisionAdapter
    risk: AdaptiveRiskAdapter
    quality: TradeQualityAdapter
    base_dir: str | None = None
    symbol: str = "XAUUSD"


@dataclass
class LatencyBreakdown:
    features_ms: float = 0.0
    decision_ms: float = 0.0
    calibration_ms: float = 0.0
    risk_ms: float = 0.0
    quality_ms: float = 0.0
    mapping_ms: float = 0.0
    total_ms: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "features_ms": round(self.features_ms, 3),
            "decision_ms": round(self.decision_ms, 3),
            "calibration_ms": round(self.calibration_ms, 3),
            "risk_ms": round(self.risk_ms, 3),
            "quality_ms": round(self.quality_ms, 3),
            "mapping_ms": round(self.mapping_ms, 3),
            "total_ms": round(self.total_ms, 3),
        }


class KernelAdapter:
    """
    Production ML signal adapter for TradingKernel.

    Receives market data, runs validated ML stack, returns TradingSignal.
    No execution, no order logic.
    """

    def __init__(self, deps: MLKernelDependencies) -> None:
        self._deps = deps
        self._last_latency = LatencyBreakdown()
        self._last_unified: UnifiedSignal | None = None
        self._last_filter_diagnostics: FilterProfileDiagnostics | None = None

    @property
    def last_latency(self) -> LatencyBreakdown:
        return self._last_latency

    @property
    def last_unified_signal(self) -> UnifiedSignal | None:
        return self._last_unified

    @property
    def last_filter_diagnostics(self) -> FilterProfileDiagnostics | None:
        return self._last_filter_diagnostics

    def _engine_inners(self) -> tuple[Any, Any]:
        range_eng = self._deps.registry.get("phase9_9")
        trend_id = resolve_active_trend_engine_id()
        trend_eng = self._deps.registry.get(trend_id)
        if range_eng is None or trend_eng is None:
            raise KernelFallbackError("registry_engines_missing")
        range_inner = getattr(range_eng, "inner", None)
        trend_inner = getattr(trend_eng, "inner", None)
        if range_inner is None or trend_inner is None:
            raise KernelFallbackError("engine_inner_missing")
        return range_inner, trend_inner

    def _replay_hold_chain(self, snapshot: dict | None) -> None:
        if not hold_chain_enabled() or not snapshot:
            return
        chain = get_hold_chain()
        chain.record_bar()
        stage = snapshot.get("stage")
        if stage:
            chain.record(HoldStage(stage))
        elif snapshot.get("direction") == "BUY":
            chain.record_buy()
        elif snapshot.get("direction") == "SELL":
            chain.record_sell()

    def _hold_chain_snapshot(
        self,
        *,
        raw_action: str,
        action: str,
        risk_allowed: bool,
        quality_allowed: bool,
        filt_result,
    ) -> dict[str, str]:
        if raw_action == "HOLD":
            return {"stage": HoldStage.DECISION.value}
        if action not in ("BUY", "SELL"):
            return {"stage": HoldStage.CALIBRATION.value}
        if not quality_allowed or not risk_allowed:
            return {"stage": HoldStage.TRADE_QUALITY.value}
        if filt_result and not filt_result.passed:
            if "rsi_filter" in filt_result.blocked_by:
                return {"stage": HoldStage.RSI_FILTER.value}
            if "adx_filter" in filt_result.blocked_by:
                return {"stage": HoldStage.ADX_FILTER.value}
        return {"direction": action}

    def _record_hold_chain(self, snapshot: dict[str, str]) -> None:
        if not hold_chain_enabled():
            return
        chain = get_hold_chain()
        chain.record_bar()
        stage = snapshot.get("stage")
        if stage:
            chain.record(HoldStage(stage))
        elif snapshot.get("direction") == "BUY":
            chain.record_buy()
        elif snapshot.get("direction") == "SELL":
            chain.record_sell()

    def produce_unified_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
    ) -> UnifiedSignal:
        t0 = time.perf_counter()
        lat = LatencyBreakdown()

        require_health(
            registry=self._deps.registry,
            base_dir=self._deps.base_dir,
        )

        t_feat = time.perf_counter()
        unified = PipelineCache.get_unified_frame(
            df,
            base_dir=self._deps.base_dir,
            symbol=market.symbol,
            timeframe=market.timeframe,
        )
        lat.features_ms = (time.perf_counter() - t_feat) * 1000
        if unified.empty:
            raise KernelFallbackError("unified_frame_empty")

        row = unified.iloc[-1]
        require_health(
            registry=self._deps.registry,
            base_dir=self._deps.base_dir,
            unified_row=row,
        )

        row_key = PipelineCache.build_prediction_cache_key(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candles=df,
            unified_row=row,
            base_dir=self._deps.base_dir,
        )
        cached = PipelineCache.get_prediction(row_key)
        if cached:
            self._last_unified = UnifiedSignal.from_dict(cached)
            lat.total_ms = (time.perf_counter() - t0) * 1000
            self._last_latency = lat
            self._replay_hold_chain(cached.get("_hold_chain"))
            return self._last_unified

        range_inner, trend_inner = self._engine_inners()
        candles = normalize_candles_for_builder(df)
        bar_index = len(candles) - 1

        ctx = PipelineCache.get_market_context(
            row,
            symbol=market.symbol,
            timeframe=market.timeframe,
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=candles,
            bar_index=bar_index,
            base_dir=self._deps.base_dir,
        )

        t_cal = time.perf_counter()
        calibrated, risk, quality = self._deps.quality.evaluate(ctx)
        lat.decision_ms = (time.perf_counter() - t_cal) * 1000 * 0.35
        lat.calibration_ms = (time.perf_counter() - t_cal) * 1000 * 0.25
        lat.risk_ms = (time.perf_counter() - t_cal) * 1000 * 0.20
        lat.quality_ms = (time.perf_counter() - t_cal) * 1000 * 0.20

        elapsed = (time.perf_counter() - t0) * 1000
        if elapsed > PIPELINE_TIMEOUT_MS:
            timeout_detail = {
                "stage": "produce_unified_signal",
                "elapsed_ms": round(elapsed, 3),
                "timeout_ms": PIPELINE_TIMEOUT_MS,
                "timeout_reason": f"pipeline_timeout:{elapsed:.1f}ms",
                "feature_source": "PipelineCache.get_unified_frame",
                "engine": str(getattr(calibrated.decision, "engine", "") or ""),
                "regime": str(getattr(calibrated.decision, "regime", "") or ""),
            }
            logger.warning("ML pipeline timeout: %s", timeout_detail)
            from tradingbot.ml.integration.timeout_diagnostics import record_pipeline_timeout

            record_pipeline_timeout(timeout_detail)
            raise KernelFallbackError(
                f"pipeline_timeout:{elapsed:.1f}ms",
                checks=timeout_detail,
            )

        decision = calibrated.decision
        raw_action = str(decision.action)
        action = str(calibrated.final_action)
        filt_settings, filter_diag = select_profitability_filter_settings(
            regime=str(decision.regime),
            engine=str(decision.engine) if decision.engine else None,
        )

        filt = None
        if action in ("BUY", "SELL") and risk.allowed and quality.allowed:
            filt = apply_profitability_filters(row.to_dict(), settings=filt_settings)
            filter_diag = attach_filter_diagnostics(filter_diag, filt)
        self._last_filter_diagnostics = filter_diag

        if action not in ("BUY", "SELL"):
            action = "HOLD"
        elif not risk.allowed or not quality.allowed:
            action = "HOLD"
        elif filt is not None and not filt.passed:
            action = "HOLD"

        hold_snap = self._hold_chain_snapshot(
            raw_action=raw_action,
            action=str(calibrated.final_action),
            risk_allowed=risk.allowed,
            quality_allowed=quality.allowed,
            filt_result=filt,
        )
        if action in ("BUY", "SELL"):
            hold_snap = {"direction": action}
        self._record_hold_chain(hold_snap)

        unified_sig = UnifiedSignal(
            engine=calibrated.decision.engine,
            regime=calibrated.decision.regime,
            direction=action,
            confidence=float(calibrated.final_confidence),
            quality=float(quality.score),
            risk=float(risk.risk_percent),
            reason=list(calibrated.decision.explanation),
            trace=list(calibrated.decision.trace) + list(getattr(quality, "trace", []) or []),
        )
        payload = unified_sig.to_dict()
        payload["_hold_chain"] = hold_snap
        PipelineCache.set_prediction(row_key, unified_sig.checksum, payload)
        self._last_unified = unified_sig

        lat.total_ms = (time.perf_counter() - t0) * 1000
        self._last_latency = lat
        log_decision_latency(lat.to_dict(), base_dir=self._deps.base_dir)
        write_engine_health(self._deps.registry.health_all(), base_dir=self._deps.base_dir)
        return unified_sig

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> TradingSignal | None:
        """Kernel-facing signal generation — replaces PriceActionStrategy path."""
        t0 = time.perf_counter()
        unified = self.produce_unified_signal(market, df)

        t_map = time.perf_counter()
        trading = map_unified_to_trading_signal(unified, market, df, config=config)
        self._last_latency.mapping_ms = (time.perf_counter() - t_map) * 1000
        self._last_latency.total_ms = (time.perf_counter() - t0) * 1000

        decision_record: dict[str, Any] = {
            "symbol": market.symbol,
            "timeframe": market.timeframe,
            "direction": unified.direction,
            "engine": unified.engine,
            "regime": unified.regime,
            "confidence": unified.confidence,
            "latency_ms": self._last_latency.to_dict(),
        }
        if self._last_filter_diagnostics is not None:
            decision_record["filter_diagnostics"] = self._last_filter_diagnostics.to_dict()
        log_kernel_decision(decision_record, base_dir=self._deps.base_dir)

        if trading.direction == SignalDirection.HOLD:
            return None
        return trading
