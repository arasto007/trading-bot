"""Phase 14.2B — engine historical quality factor."""

from __future__ import annotations

from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics


def engine_performance_factor(engine: str | None, history: HistoricalMetrics) -> tuple[float, str]:
    if not engine:
        return 1.0, "no engine selected"
    factor = history.engine_quality_factor(engine)
    trades = history.engine_trade_count.get(engine, 0)
    if trades > 0 and trades < 100:
        factor *= 0.9
        return round(factor, 4), f"{engine} limited sample ({trades} trades) ×0.9"
    return round(factor, 4), f"{engine} validated quality factor {factor:.2f}"
