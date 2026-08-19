"""Phase 20A — observed ML kernel adapter (filter + decision logging)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.integration.kernel_adapter import KernelAdapter
from tradingbot.ml.phase19c.filters import apply_profitability_filters
from tradingbot.ml.phase20a.reporter import Phase20aReporter
from tradingbot.ml.phase20a.safety_monitor import Phase20aSafetyMonitor


class Phase20aObservedAdapter:
    """Wraps KernelAdapter — logs signals, filters, latency without changing core logic."""

    def __init__(
        self,
        inner: KernelAdapter,
        *,
        reporter: Phase20aReporter,
        safety: Phase20aSafetyMonitor,
    ) -> None:
        self._inner = inner
        self._reporter = reporter
        self._safety = safety

    @property
    def last_latency(self):
        return self._inner.last_latency

    @property
    def last_unified_signal(self):
        return self._inner.last_unified_signal

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> TradingSignal | None:
        ts = datetime.now(timezone.utc).isoformat()
        row = df.iloc[-1].to_dict() if not df.empty else {}
        filt = apply_profitability_filters(row)

        t0 = time.perf_counter()
        signal = self._inner.generate_signal(market, df, correlation_data, config=config)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        unified = self._inner.last_unified_signal
        direction = unified.direction if unified else "HOLD"
        if direction in ("BUY", "SELL"):
            self._safety.record_signal()

        self._reporter.log_signal({
            "timestamp": ts,
            "symbol": market.symbol,
            "timeframe": market.timeframe,
            "direction": direction,
            "filter_passed": filt.passed,
            "filter_blocked_by": filt.blocked_by,
            "rsi": filt.rsi,
            "adx": filt.adx,
            "confidence": unified.confidence if unified else None,
            "engine": unified.engine if unified else None,
            "regime": unified.regime if unified else None,
            "latency_ms": round(latency_ms, 2),
        })
        self._reporter.log_latency({
            "timestamp": ts,
            "latency_ms": round(latency_ms, 2),
            "symbol": market.symbol,
        })
        self._safety.record_latency(latency_ms)

        if unified and unified.engine:
            trend_eng = str(unified.engine)
            if trend_eng and unified.regime == "RANGE" and direction in ("BUY", "SELL"):
                self._safety.record_engine_divergence({
                    "regime": unified.regime,
                    "engine": trend_eng,
                    "direction": direction,
                })

        return signal
