"""Phase 15C — monitoring observer (wraps KernelAdapter without changing trading logic)."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.kernel_adapter import KernelAdapter
from tradingbot.ml.monitoring.bundle_monitor import BundleMonitor
from tradingbot.ml.monitoring.decision_logger import DecisionLogger
from tradingbot.ml.monitoring.engine_monitor import EngineMonitor
from tradingbot.ml.monitoring.fallback_monitor import FallbackMonitor
from tradingbot.ml.monitoring.health_monitor import HealthMonitor
from tradingbot.ml.monitoring.latency_monitor import LatencyMonitor
from tradingbot.ml.monitoring.performance_monitor import PerformanceMonitor
from tradingbot.ml.monitoring.prediction_monitor import PredictionMonitor
from tradingbot.ml.monitoring.config import HEALTH_CHECK_EVERY_N_BARS
from tradingbot.ml.phase15a.config import BUNDLE_VERSION as TREND_BUNDLE_VERSION


class MonitoringHub:
    """Central observability hub — thread-safe recorders."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = base_dir
        self.decisions = DecisionLogger(base_dir)
        self.latency = LatencyMonitor(base_dir)
        self.engines = EngineMonitor()
        self.fallbacks = FallbackMonitor(base_dir)
        self.health = HealthMonitor(base_dir)
        self.predictions = PredictionMonitor(base_dir)
        self.performance = PerformanceMonitor(base_dir)
        self.bundles = BundleMonitor(base_dir)
        self._bar_count = 0
        self._last_health: dict[str, Any] = {}

    def maybe_health_check(self, registry: Any) -> dict[str, Any] | None:
        self._bar_count += 1
        if self._bar_count % HEALTH_CHECK_EVERY_N_BARS == 0:
            self._last_health = self.health.check(registry)
            return self._last_health
        return None

    @property
    def last_health(self) -> dict[str, Any]:
        return self._last_health


class MonitoredKernelAdapter:
    """Observability wrapper around KernelAdapter — no trading logic changes."""

    def __init__(self, inner: KernelAdapter, hub: MonitoringHub | None = None) -> None:
        self._inner = inner
        self._hub = hub or MonitoringHub(inner._deps.base_dir)

    @property
    def last_latency(self):
        return self._inner.last_latency

    @property
    def last_unified_signal(self):
        return self._inner.last_unified_signal

    def produce_unified_signal(self, market, df):
        return self._inner.produce_unified_signal(market, df)

    def _sync_engine_meta(self) -> None:
        reg = self._inner._deps.registry
        for eid in ("phase9_9", "trend_rf_v40"):
            eng = reg.get(eid)
            if eng is None:
                self._hub.engines.set_engine_meta(eid, checksum=None, version=None, available=False)
                continue
            self._hub.engines.set_engine_meta(
                eid,
                checksum=eng.checksum(),
                version=eng.version(),
                available=eng.health().get("status") == "OK",
            )

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> TradingSignal | None:
        self._sync_engine_meta()
        self._hub.maybe_health_check(self._inner._deps.registry)

        t0 = time.perf_counter()
        try:
            signal = self._inner.generate_signal(market, df, correlation_data, config=config)
        except KernelFallbackError as exc:
            self._hub.fallbacks.record(exc.reason, detail=exc.checks)
            self._hub.performance.ingest_fallback()
            raise

        unified = self._inner.last_unified_signal
        lat = self._inner.last_latency.to_dict()
        self._hub.latency.record_from_breakdown(lat)

        if unified is not None:
            trace_id = ""
            if signal and signal.metadata:
                trace_id = str(signal.metadata.get("trace_id", ""))
            elif unified.checksum:
                trace_id = unified.checksum[:16]

            accepted = unified.direction in ("BUY", "SELL") and signal is not None
            block_reason = None if accepted else "hold_or_blocked"
            meta = signal.metadata if signal else {}
            prob = float(meta.get("probability", unified.confidence)) if meta else unified.confidence

            record = self._hub.decisions.log(
                symbol=market.symbol,
                timeframe=market.timeframe,
                regime=unified.regime,
                engine=unified.engine,
                direction=unified.direction,
                confidence=unified.confidence,
                quality=unified.quality,
                risk=unified.risk,
                latency_ms=lat,
                trace_id=trace_id,
                checksum=unified.checksum,
                decision_reason=list(unified.reason),
                bundle_version=TREND_BUNDLE_VERSION,
            )
            self._hub.performance.ingest_decision(record)
            self._hub.predictions.record(
                engine=unified.engine,
                probability=prob,
                confidence=unified.confidence,
                accepted=accepted,
                block_reason=block_reason,
                regime=unified.regime,
            )
            for layer, ms in (
                ("decision", lat.get("decision_ms", 0)),
                ("calibration", lat.get("calibration_ms", 0)),
                ("risk", lat.get("risk_ms", 0)),
                ("quality", lat.get("quality_ms", 0)),
            ):
                self._hub.engines.record_call(layer, success=True, latency_ms=ms)
            for eid in (unified.engine,):
                if eid:
                    self._hub.engines.record_call(str(eid), success=accepted, latency_ms=lat.get("total_ms", 0))

        elapsed = (time.perf_counter() - t0) * 1000
        self._hub.engines.record_call("decision", success=True, latency_ms=elapsed)
        return signal
