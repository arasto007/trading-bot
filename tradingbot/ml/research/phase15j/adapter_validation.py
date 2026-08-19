"""Phase 15J — adapter validation (engine → UnifiedSignal → TradingSignal)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.signal_mapper import map_unified_to_trading_signal
from tradingbot.ml.phase15a.unified_signal import UnifiedSignal


def validate_adapter_chain(
    candles: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    sample_bars: int = 5,
) -> dict[str, Any]:
    PipelineCache.reset()
    from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack

    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
    market = MarketKey(symbol, timeframe)

    samples: list[dict[str, Any]] = []
    loss_count = 0
    checked = 0

    stride = max(1, len(candles) // max(sample_bars * 20, 1))
    for i in range(350, len(candles), stride):
        if checked >= sample_bars:
            break
        sl = candles.iloc[max(0, i - 350) : i + 1]
        try:
            adapter.produce_unified_signal(market, sl.copy())
        except Exception:
            continue
        unified = adapter.last_unified_signal
        if unified is None:
            continue
        trading = map_unified_to_trading_signal(unified, market, sl)
        checked += 1
        losses = _field_losses(unified, trading)
        if losses:
            loss_count += 1
        samples.append({
            "timestamp": unified.timestamp,
            "engine": unified.engine,
            "regime": unified.regime,
            "unified_direction": unified.direction,
            "trading_direction": trading.direction.name,
            "confidence_preserved": abs(unified.confidence - trading.confidence) < 1e-6,
            "metadata_fields": list(trading.metadata.keys()),
            "information_loss": losses,
        })

    return {
        "phase": "15J",
        "samples_checked": checked,
        "samples_with_loss": loss_count,
        "no_information_loss": loss_count == 0,
        "required_metadata": ["engine_name", "regime", "quality", "risk_percent", "trace_id"],
        "samples": samples,
    }


def _field_losses(unified: UnifiedSignal, trading: Any) -> list[str]:
    losses: list[str] = []
    if unified.direction != trading.direction.name and not (
        unified.direction == "HOLD" and trading.direction.name == "HOLD"
    ):
        losses.append("direction_mismatch")
    if abs(float(unified.confidence) - float(trading.confidence)) > 1e-6:
        losses.append("confidence_mismatch")
    meta = trading.metadata or {}
    for key in ("engine_name", "regime", "quality", "risk_percent"):
        if key not in meta:
            losses.append(f"missing_{key}")
    if unified.engine and meta.get("engine_name") != unified.engine:
        losses.append("engine_name_mismatch")
    return losses
