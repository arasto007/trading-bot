"""Phase 14.3 — historical engine performance modifier."""

from __future__ import annotations

from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics


def engine_history_modifier(engine: str | None, history: HistoricalMetrics | None) -> tuple[float, str]:
    if not engine or history is None:
        return 1.0, "no engine history"
    factor = history.engine_quality_factor(engine)
    trades = history.engine_trade_count.get(engine, 0)
    if trades >= 500:
        return 1.0, f"{engine} proven sample ({trades} trades)"
    if trades >= 100:
        return min(1.0, factor), f"{engine} validated ({trades} trades)"
    return 0.95, f"{engine} limited history"
