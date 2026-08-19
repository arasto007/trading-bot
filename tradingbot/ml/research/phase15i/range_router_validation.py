"""Phase 15I — range router validation."""

from __future__ import annotations

from tradingbot.ml.research.phase15i.router_balance import audit_router_balance


def validate_range_router(
    candles,
    dataset,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    stride: int = 15,
) -> dict:
    audit = audit_router_balance(
        candles, dataset,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe,
        days=days, stride=stride,
    )
    return {
        "phase": "15I",
        **audit,
        "phase9_9_selected": audit["engine_selection"].get("phase9_9", 0),
        "phase9_9_skipped": audit.get("range_skipped_mismatch", 0),
        "phase9_9_blocked": audit.get("blocked_regime_count", 0),
        "routing_correct": audit.get("router_calls_phase9_9_correctly", False),
    }
